#!/usr/bin/env python3
"""
Web Tools - Web Scraping and YouTube Summary
- Fetch and convert web pages to markdown
- Extract YouTube video transcripts
- Summarize content using local LLM
- Chunk and store in ChromaDB for RAG persistence
"""

import os
import re
import json
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict
from urllib.parse import urlparse, parse_qs

import requests

# ChromaDB for vector storage
try:
    import chromadb
    from chromadb.config import Settings

    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("⚠️ ChromaDB not installed: pip install chromadb")

# Optional imports with fallbacks
try:
    from bs4 import BeautifulSoup

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    print("âš ï¸ BeautifulSoup not installed: pip install beautifulsoup4")

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

    YT_TRANSCRIPT_AVAILABLE = True
    # Try to import proxy support
    try:
        from youtube_transcript_api.proxies import WebshareProxyConfig

        PROXY_SUPPORT = True
    except ImportError:
        PROXY_SUPPORT = False
except ImportError:
    YT_TRANSCRIPT_AVAILABLE = False
    PROXY_SUPPORT = False
    print("⚠️ YouTube Transcript API not installed: pip install youtube-transcript-api[proxy]")

# Check for browser cookie support
try:
    import browser_cookie3

    BROWSER_COOKIES_AVAILABLE = True
except ImportError:
    BROWSER_COOKIES_AVAILABLE = False

# Check for yt-dlp as fallback for YouTube
try:
    import yt_dlp

    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

try:
    import html2text

    HTML2TEXT_AVAILABLE = True
except ImportError:
    HTML2TEXT_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebScraper:
    """Web scraping and content extraction."""

    def __init__(self, output_dir: str = "exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Default headers to avoid blocks
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        # HTML to Markdown converter
        if HTML2TEXT_AVAILABLE:
            self.h2t = html2text.HTML2Text()
            self.h2t.ignore_links = False
            self.h2t.ignore_images = False
            self.h2t.body_width = 0  # No wrapping
        else:
            self.h2t = None

    def fetch_url(self, url: str, timeout: int = 30) -> Tuple[str, bool]:
        """Fetch URL content. Returns (content, success)."""
        try:
            response = requests.get(url, headers=self.headers, timeout=timeout)
            response.raise_for_status()
            return response.text, True
        except requests.exceptions.RequestException as e:
            return f"Error fetching URL: {e}", False

    def html_to_markdown(self, html: str, url: str = "") -> str:
        """Convert HTML to Markdown."""
        if not BS4_AVAILABLE:
            return "Error: BeautifulSoup not installed"

        soup = BeautifulSoup(html, "html.parser")

        # Remove unwanted elements
        for tag in soup.find_all(
            ["script", "style", "nav", "footer", "aside", "iframe", "noscript"]
        ):
            tag.decompose()

        # Extract title
        title = ""
        if soup.title:
            title = soup.title.string or ""

        # Extract main content (try common content containers)
        main_content = None
        for selector in ["article", "main", '[role="main"]', ".content", ".post", "#content"]:
            main_content = soup.select_one(selector)
            if main_content:
                break

        if not main_content:
            main_content = soup.body or soup

        # Convert to markdown
        if self.h2t:
            markdown = self.h2t.handle(str(main_content))
        else:
            # Fallback: basic text extraction
            markdown = main_content.get_text(separator="\n", strip=True)

        # Build final markdown
        output = []
        output.append(f"# {title}\n")
        output.append(f"**Source:** {url}")
        output.append(f"**Fetched:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        output.append("---\n")
        output.append(markdown)

        return "\n".join(output)

    def scrape_to_markdown(self, url: str) -> Tuple[str, str, bool]:
        """
        Scrape URL and convert to markdown.
        Returns (markdown_content, filename, success)
        """
        logger.info(f"Scraping: {url}")

        # Fetch content
        html, success = self.fetch_url(url)
        if not success:
            return html, "", False

        # Convert to markdown
        markdown = self.html_to_markdown(html, url)

        # Generate filename from URL
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        path = parsed.path.strip("/").replace("/", "_")[:50] or "index"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"web_{domain}_{path}_{timestamp}.md"
        filename = re.sub(r'[<>:"/\\|?*]', "_", filename)  # Sanitize

        return markdown, filename, True

    def save_markdown(self, content: str, filename: str) -> str:
        """Save markdown to file. Returns filepath."""
        filepath = self.output_dir / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Saved: {filepath}")
        return str(filepath)

    def scrape_and_save(self, url: str) -> Tuple[str, bool]:
        """Scrape URL and save to markdown file. Returns (filepath, success)."""
        markdown, filename, success = self.scrape_to_markdown(url)
        if not success:
            return markdown, False

        filepath = self.save_markdown(markdown, filename)
        return filepath, True


class YouTubeSummarizer:
    """YouTube video transcript extraction, summarization, and RAG storage."""

    def __init__(
        self,
        output_dir: str = "exports",
        cookie_file: str = None,
        chroma_db_path: str = "./chroma_db",
        ollama_url: str = "http://localhost:11434",
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cookie_file = cookie_file
        self._yt_api = None
        self.ollama_url = ollama_url
        self.chroma_db_path = chroma_db_path
        self._chroma_client = None
        self._youtube_collection = None

    def _get_chroma_collection(self):
        """Get or create the YouTube content collection in ChromaDB."""
        if self._youtube_collection is not None:
            return self._youtube_collection

        if not CHROMADB_AVAILABLE:
            logger.warning("ChromaDB not available - content won't be persisted")
            return None

        try:
            # Use separate path for web_tools to avoid conflict with production_rag
            youtube_db_path = self.chroma_db_path + "_youtube"
            
            # Try new PersistentClient first (chromadb >= 0.4)
            try:
                self._chroma_client = chromadb.PersistentClient(
                    path=youtube_db_path,
                    settings=Settings(anonymized_telemetry=False, allow_reset=True),
                )
            except AttributeError:
                # Fall back to legacy Client for chromadb < 0.4
                self._chroma_client = chromadb.Client(
                    Settings(
                        chroma_db_impl="duckdb+parquet",
                        persist_directory=youtube_db_path,
                        anonymized_telemetry=False
                    )
                )
            self._youtube_collection = self._chroma_client.get_or_create_collection(
                name="youtube_content", metadata={"hnsw:space": "cosine"}
            )
            logger.info(
                f"✅ ChromaDB youtube_content collection ready ({self._youtube_collection.count()} documents)"
            )
            return self._youtube_collection
        except Exception as e:
            logger.error(f"ChromaDB initialization failed: {e}")
            return None

    def chunk_transcript(
        self, transcript: str, chunk_size: int = 1000, overlap: int = 200
    ) -> List[Dict]:
        """
        Split transcript into overlapping chunks for better RAG retrieval.
        Returns list of dicts with 'text', 'start_char', 'end_char'.
        """
        chunks = []
        text = transcript.strip()

        if len(text) <= chunk_size:
            return [{"text": text, "start_char": 0, "end_char": len(text), "chunk_index": 0}]

        start = 0
        chunk_index = 0

        while start < len(text):
            end = start + chunk_size

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end within last 200 chars of chunk
                search_start = max(start + chunk_size - 200, start)
                sentence_ends = []
                for pattern in [". ", "? ", "! ", ".\n", "?\n", "!\n"]:
                    pos = text.rfind(pattern, search_start, end + 50)
                    if pos != -1:
                        sentence_ends.append(pos + len(pattern))

                if sentence_ends:
                    end = max(sentence_ends)

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(
                    {
                        "text": chunk_text,
                        "start_char": start,
                        "end_char": end,
                        "chunk_index": chunk_index,
                    }
                )
                chunk_index += 1

            start = end - overlap
            if start <= chunks[-1]["start_char"] if chunks else 0:
                start = end

        logger.info(f"📝 Split transcript into {len(chunks)} chunks")
        return chunks

    def summarize_with_ollama(
        self, text: str, model: str = "llama3.2:3b", max_tokens: int = 500, context: str = ""
    ) -> Tuple[str, bool]:
        """
        Summarize text using local Ollama LLM.
        Returns (summary, success).
        """
        try:
            prompt = f"""Summarize the following content concisely. Focus on key points, main topics, and important details.
{f"Context: {context}" if context else ""}

Content to summarize:
{text[:8000]}

Provide a clear, structured summary:"""

            # FXJEFE Local Larry: Increased timeout for Ollama summarization (complex docs can take time)
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": 0.3},
                },
                timeout=600,  # 10 minutes
            )

            if response.status_code == 200:
                result = response.json()
                summary = result.get("response", "").strip()
                logger.info(f"✅ Generated summary ({len(summary)} chars)")
                return summary, True
            else:
                return f"Ollama error: {response.status_code}", False

        except requests.exceptions.ConnectionError:
            return "Error: Ollama not running. Start with 'ollama serve'", False
        except Exception as e:
            return f"Summarization error: {e}", False

    def store_in_chromadb(
        self, video_id: str, video_info: Dict, chunks: List[Dict], summary: str = None
    ) -> bool:
        """
        Store video chunks and metadata in ChromaDB for RAG retrieval.
        """
        collection = self._get_chroma_collection()
        if collection is None:
            return False

        try:
            documents = []
            ids = []
            metadatas = []

            # Store each chunk
            for chunk in chunks:
                chunk_id = f"yt_{video_id}_chunk_{chunk['chunk_index']}"
                ids.append(chunk_id)
                documents.append(chunk["text"])
                metadatas.append(
                    {
                        "video_id": video_id,
                        "title": video_info.get("title", "Unknown"),
                        "author": video_info.get("author", "Unknown"),
                        "chunk_index": chunk["chunk_index"],
                        "start_char": chunk["start_char"],
                        "end_char": chunk["end_char"],
                        "type": "transcript_chunk",
                        "indexed_at": datetime.now().isoformat(),
                    }
                )

            # Store summary as a separate document
            if summary:
                ids.append(f"yt_{video_id}_summary")
                documents.append(summary)
                metadatas.append(
                    {
                        "video_id": video_id,
                        "title": video_info.get("title", "Unknown"),
                        "author": video_info.get("author", "Unknown"),
                        "type": "summary",
                        "chunk_count": len(chunks),
                        "indexed_at": datetime.now().isoformat(),
                    }
                )

            # Upsert to collection
            collection.upsert(documents=documents, ids=ids, metadatas=metadatas)
            logger.info(f"💾 Stored {len(ids)} documents in ChromaDB for video {video_id}")
            return True

        except Exception as e:
            logger.error(f"ChromaDB storage error: {e}")
            return False

    def search_youtube_content(
        self, query: str, n_results: int = 5, video_id: str = None
    ) -> List[Dict]:
        """
        Search stored YouTube content in ChromaDB.
        Optionally filter by video_id.
        """
        collection = self._get_chroma_collection()
        if collection is None or collection.count() == 0:
            return []

        try:
            where_filter = None
            if video_id:
                where_filter = {"video_id": video_id}

            results = collection.query(
                query_texts=[query],
                n_results=min(n_results, collection.count()),
                where=where_filter,
            )

            output = []
            for i in range(len(results["documents"][0])):
                output.append(
                    {
                        "text": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i]
                        if results.get("distances")
                        else None,
                    }
                )

            return output

        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_stored_videos(self) -> List[Dict]:
        """Get list of all stored YouTube videos."""
        collection = self._get_chroma_collection()
        if collection is None or collection.count() == 0:
            return []

        try:
            # Get all summaries (one per video)
            results = collection.get(where={"type": "summary"}, include=["metadatas"])

            videos = []
            for metadata in results.get("metadatas", []):
                videos.append(
                    {
                        "video_id": metadata.get("video_id"),
                        "title": metadata.get("title"),
                        "author": metadata.get("author"),
                        "chunk_count": metadata.get("chunk_count"),
                        "indexed_at": metadata.get("indexed_at"),
                    }
                )

            return videos

        except Exception as e:
            logger.error(f"Error getting stored videos: {e}")
            return []

    def _get_api(self) -> "YouTubeTranscriptApi":
        """Get YouTubeTranscriptApi instance with cookie support if available."""
        if self._yt_api is not None:
            return self._yt_api

        # Try cookie file first
        if self.cookie_file and os.path.exists(self.cookie_file):
            logger.info(f"Using cookie file: {self.cookie_file}")
            self._yt_api = YouTubeTranscriptApi(cookie_path=self.cookie_file)
            return self._yt_api

        # Try browser cookies if available
        if BROWSER_COOKIES_AVAILABLE:
            try:
                # Try Chrome first, then Edge, then Firefox
                cookie_path = self._extract_browser_cookies()
                if cookie_path:
                    logger.info("Using extracted browser cookies")
                    self._yt_api = YouTubeTranscriptApi(cookie_path=cookie_path)
                    return self._yt_api
            except Exception as e:
                logger.warning(f"Browser cookie extraction failed: {e}")

        # Fall back to no cookies
        self._yt_api = YouTubeTranscriptApi()
        return self._yt_api

    def _extract_browser_cookies(self) -> Optional[str]:
        """Extract YouTube cookies from browser and save to Netscape format file."""
        if not BROWSER_COOKIES_AVAILABLE:
            return None

        cookie_file = self.output_dir / "youtube_cookies.txt"

        # Try different browsers
        browsers = [
            ("chrome", browser_cookie3.chrome),
            ("edge", browser_cookie3.edge),
            ("firefox", browser_cookie3.firefox),
        ]

        for browser_name, browser_func in browsers:
            try:
                cj = browser_func(domain_name=".youtube.com")
                cookies = list(cj)
                if cookies:
                    # Write Netscape format cookie file
                    with open(cookie_file, "w") as f:
                        f.write("# Netscape HTTP Cookie File\n")
                        for cookie in cookies:
                            secure = "TRUE" if cookie.secure else "FALSE"
                            http_only = (
                                "TRUE"
                                if getattr(cookie, "_rest", {}).get("HttpOnly", False)
                                else "FALSE"
                            )
                            expiry = cookie.expires if cookie.expires else 0
                            f.write(
                                f".youtube.com\tTRUE\t{cookie.path}\t{secure}\t{expiry}\t{cookie.name}\t{cookie.value}\n"
                            )
                    logger.info(f"Extracted {len(cookies)} cookies from {browser_name}")
                    return str(cookie_file)
            except Exception as e:
                logger.debug(f"Could not get cookies from {browser_name}: {e}")
                continue

        return None

    def set_cookie_file(self, cookie_path: str):
        """Set cookie file for YouTube authentication."""
        self.cookie_file = cookie_path
        self._yt_api = None  # Reset to reload with new cookies
        logger.info(f"Cookie file set: {cookie_path}")

    def _get_transcript_via_ytdlp(self, video_id: str) -> Tuple[str, bool]:
        """
        Fallback method: Use yt-dlp to get subtitles.
        yt-dlp has better anti-bot bypass mechanisms.
        """
        if not YTDLP_AVAILABLE:
            return "yt-dlp not available", False

        import json

        url = f"https://www.youtube.com/watch?v={video_id}"

        # yt-dlp options to just extract info with subtitles
        opts = {
            "skip_download": True,
            "writesubtitles": False,
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {"youtube": {"player_client": ["android_sdkless", "web"]}},
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

                # Check for subtitles or auto-captions
                subtitles = info.get("subtitles", {})
                auto_captions = info.get("automatic_captions", {})

                # Prefer manual subtitles, fall back to auto
                sub_data = None
                for lang in ["en", "en-US", "en-GB"]:
                    if lang in subtitles:
                        sub_data = subtitles[lang]
                        break
                    if lang in auto_captions:
                        sub_data = auto_captions[lang]
                        break

                if not sub_data:
                    # Try any available subtitle
                    if subtitles:
                        sub_data = list(subtitles.values())[0]
                    elif auto_captions:
                        sub_data = list(auto_captions.values())[0]

                if not sub_data:
                    return "No subtitles found", False

                # Find best format (json3 preferred for parsing)
                sub_url = None
                for fmt in sub_data:
                    if fmt.get("ext") == "json3":
                        sub_url = fmt.get("url")
                        break

                if not sub_url:
                    # Fall back to any format
                    sub_url = sub_data[0].get("url")

                if not sub_url:
                    return "Could not get subtitle URL", False

                # Fetch the subtitle content
                response = requests.get(sub_url, timeout=30)
                if response.status_code != 200:
                    return f"Failed to fetch subtitles: HTTP {response.status_code}", False

                content = response.text

                # Parse JSON3 format
                try:
                    data = json.loads(content)
                    events = data.get("events", [])
                    text_parts = []
                    for event in events:
                        segs = event.get("segs", [])
                        for seg in segs:
                            t = seg.get("utf8", "").strip()
                            if t and t != "\n":
                                text_parts.append(t)
                    if text_parts:
                        return " ".join(text_parts), True
                except (json.JSONDecodeError, TypeError):
                    pass

                # Try to parse as plain text/VTT
                lines = []
                for line in content.split("\n"):
                    line = line.strip()
                    if not line or "-->" in line or line.startswith("WEBVTT") or line.isdigit():
                        continue
                    line = re.sub(r"<[^>]+>", "", line)
                    if line:
                        lines.append(line)
                if lines:
                    return " ".join(lines), True

                return "Could not parse subtitle content", False

        except Exception as e:
            logger.debug(f"yt-dlp extraction failed: {e}")
            return f"yt-dlp failed: {str(e)[:200]}", False

    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        """Extract video ID from various YouTube URL formats."""
        patterns = [
            r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
            r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)

        # Try query string
        parsed = urlparse(url)
        if "youtube.com" in parsed.netloc:
            qs = parse_qs(parsed.query)
            if "v" in qs:
                return qs["v"][0]

        return None

    def get_video_info(self, video_id: str) -> Dict:
        """Get basic video info using oembed API."""
        try:
            url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "title": data.get("title", "Unknown"),
                    "author": data.get("author_name", "Unknown"),
                    "thumbnail": data.get("thumbnail_url", ""),
                }
        except Exception as e:
            logger.warning(f"Could not fetch video info: {e}")

        return {"title": "Unknown", "author": "Unknown", "thumbnail": ""}

    def get_transcript(self, video_id: str, languages: List[str] = None) -> Tuple[str, bool]:
        """
        Get video transcript with automatic cookie support for IP block bypass.
        Returns (transcript_text, success)
        """
        if not YT_TRANSCRIPT_AVAILABLE:
            return "Error: youtube-transcript-api not installed", False

        languages = languages or ["en", "en-US", "en-GB"]

        try:
            # Use cookie-enabled API instance
            yt = self._get_api()
            transcript = yt.fetch(video_id, languages=languages)

            # Format with timestamps - entries are FetchedTranscriptSnippet objects
            formatted = []
            for entry in transcript:
                start = int(entry.start)
                minutes, seconds = divmod(start, 60)
                hours, minutes = divmod(minutes, 60)

                if hours > 0:
                    timestamp = f"[{hours}:{minutes:02d}:{seconds:02d}]"
                else:
                    timestamp = f"[{minutes}:{seconds:02d}]"

                text = entry.text.replace("\n", " ")
                formatted.append(f"{timestamp} {text}")

            return "\n".join(formatted), True

        except TranscriptsDisabled:
            return "Transcripts are disabled for this video", False
        except NoTranscriptFound:
            return "No transcript found for this video", False
        except Exception as e:
            error_msg = str(e)
            if "IP" in error_msg or "blocked" in error_msg.lower():
                # Try yt-dlp fallback
                logger.info("IP blocked, trying yt-dlp fallback...")
                if YTDLP_AVAILABLE:
                    yt_result, yt_success = self._get_transcript_via_ytdlp(video_id)
                    if yt_success:
                        return yt_result, True

                return (
                    f"YouTube IP block detected. Your browser may need to be logged into YouTube.\n"
                    f"Try: Close Edge browser completely, then run the command again.\n"
                    f"\nOriginal error: {e}"
                ), False
            return f"Error fetching transcript: {e}", False

    def get_transcript_plain(self, video_id: str) -> Tuple[str, bool]:
        """Get transcript without timestamps (for summarization)."""
        if not YT_TRANSCRIPT_AVAILABLE and not YTDLP_AVAILABLE:
            return "Error: youtube-transcript-api or yt-dlp not installed", False

        try:
            # Try youtube-transcript-api first
            if YT_TRANSCRIPT_AVAILABLE:
                yt = self._get_api()
                transcript = yt.fetch(video_id, languages=["en", "en-US", "en-GB"])
                text = " ".join([entry.text.replace("\n", " ") for entry in transcript])
                return text, True

        except Exception as e:
            error_msg = str(e)
            if "IP" in error_msg or "blocked" in error_msg.lower():
                # Try yt-dlp fallback
                logger.info("IP blocked, trying yt-dlp fallback...")
                if YTDLP_AVAILABLE:
                    return self._get_transcript_via_ytdlp(video_id)
                return "YouTube IP block detected. yt-dlp not available as fallback.", False
            return f"Error: {e}", False

    def create_markdown(
        self, video_id: str, url: str, include_timestamps: bool = True
    ) -> Tuple[str, str, bool]:
        """
        Create markdown document from YouTube video.
        Returns (markdown_content, filename, success)
        """
        logger.info(f"Processing YouTube video: {video_id}")

        # Get video info
        info = self.get_video_info(video_id)

        # Get transcript
        if include_timestamps:
            transcript, success = self.get_transcript(video_id)
        else:
            transcript, success = self.get_transcript_plain(video_id)

        if not success:
            return transcript, "", False

        # Build markdown
        output = []
        output.append(f"# {info['title']}\n")
        output.append(f"**Channel:** {info['author']}")
        output.append(f"**URL:** {url}")
        output.append(f"**Video ID:** {video_id}")
        output.append(f"**Fetched:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        if info["thumbnail"]:
            output.append(f"![Thumbnail]({info['thumbnail']})\n")

        output.append("---\n")
        output.append("## Transcript\n")
        output.append(transcript)

        markdown = "\n".join(output)

        # Generate filename
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", info["title"])[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"youtube_{safe_title}_{timestamp}.md"

        return markdown, filename, True

    def save_markdown(self, content: str, filename: str) -> str:
        """Save markdown to file. Returns filepath."""
        filepath = self.output_dir / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Saved: {filepath}")
        return str(filepath)

    def process_video(
        self,
        url: str,
        include_timestamps: bool = True,
        summarize: bool = True,
        store_in_db: bool = True,
        summary_model: str = "llama3.2:3b",
    ) -> Tuple[str, bool]:
        """
        Process YouTube video: extract transcript, summarize, chunk, and store in DB.

        Args:
            url: YouTube video URL
            include_timestamps: Include timestamps in markdown output
            summarize: Generate LLM summary of the content
            store_in_db: Store chunks and summary in ChromaDB for RAG
            summary_model: Ollama model to use for summarization

        Returns (filepath_or_error, success)
        """
        # Extract video ID
        video_id = self.extract_video_id(url)
        if not video_id:
            return "Could not extract video ID from URL", False

        # Get video info
        video_info = self.get_video_info(video_id)

        # Get plain transcript for processing
        plain_transcript, success = self.get_transcript_plain(video_id)
        if not success:
            return plain_transcript, False

        # Generate summary if requested
        summary = None
        if summarize:
            logger.info(f"🤖 Generating summary with {summary_model}...")
            context = f"YouTube video: {video_info.get('title', 'Unknown')} by {video_info.get('author', 'Unknown')}"
            summary, sum_success = self.summarize_with_ollama(
                plain_transcript, model=summary_model, context=context
            )
            if not sum_success:
                logger.warning(f"Summary generation failed: {summary}")
                summary = None

        # Chunk transcript for RAG storage
        chunks = []
        if store_in_db:
            chunks = self.chunk_transcript(plain_transcript, chunk_size=1000, overlap=200)

            # Store in ChromaDB
            stored = self.store_in_chromadb(video_id, video_info, chunks, summary)
            if stored:
                logger.info(f"✅ Video content stored in ChromaDB ({len(chunks)} chunks)")
            else:
                logger.warning("Failed to store in ChromaDB")

        # Create enhanced markdown with summary
        markdown, filename, md_success = self.create_markdown(video_id, url, include_timestamps)
        if not md_success:
            return markdown, False

        # Inject summary into markdown if available
        if summary:
            # Insert summary after the header section
            parts = markdown.split("---\n")
            if len(parts) >= 2:
                enhanced_md = (
                    parts[0]
                    + "---\n\n## AI Summary\n\n"
                    + summary
                    + "\n\n---\n"
                    + "---\n".join(parts[1:])
                )
                markdown = enhanced_md

        # Add storage info to markdown
        if store_in_db and chunks:
            storage_note = (
                f"\n\n---\n*📦 Stored in RAG database: {len(chunks)} chunks for semantic search*\n"
            )
            markdown += storage_note

        # Save
        filepath = self.save_markdown(markdown, filename)
        return filepath, True

    def process_video_simple(self, url: str, include_timestamps: bool = True) -> Tuple[str, bool]:
        """
        Simple video processing without summarization or DB storage.
        For quick transcript extraction only.
        """
        return self.process_video(url, include_timestamps, summarize=False, store_in_db=False)

    def get_video_summary(self, url: str, model: str = "llama3.2:3b") -> Optional[str]:
        """
        Convenience method to just get a summary string for a video.
        Useful for bypassing state issues by using fresh instances.
        """
        video_id = self.extract_video_id(url)
        if not video_id:
            return None

        transcript, success = self.get_transcript_plain(video_id)
        if not success:
            return None

        summary, success = self.summarize_with_ollama(transcript, model=model)
        return summary if success else None


def get_web_scraper(output_dir: str = "exports") -> WebScraper:
    """Get a WebScraper instance."""
    return WebScraper(output_dir)


def get_youtube_summarizer(
    output_dir: str = "exports",
    chroma_db_path: str = "./chroma_db",
    ollama_url: str = "http://localhost:11434",
) -> YouTubeSummarizer:
    """
    Get a YouTubeSummarizer instance with ChromaDB and Ollama integration.

    Args:
        output_dir: Directory to save markdown files
        chroma_db_path: Path to ChromaDB persistent storage
        ollama_url: URL of Ollama server
    """
    return YouTubeSummarizer(output_dir, chroma_db_path=chroma_db_path, ollama_url=ollama_url)


# CLI for testing
if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("Web Tools - Test Suite")
    print("=" * 60)

    # Check dependencies
    print("\nðŸ“¦ Dependencies:")
    print(f"  BeautifulSoup4: {'âœ…' if BS4_AVAILABLE else 'âŒ'}")
    print(f"  html2text: {'âœ…' if HTML2TEXT_AVAILABLE else 'âŒ'}")
    print(f"  YouTube Transcript API: {'âœ…' if YT_TRANSCRIPT_AVAILABLE else 'âŒ'}")

    if len(sys.argv) > 1:
        url = sys.argv[1]

        if "youtube.com" in url or "youtu.be" in url:
            print(f"\nðŸŽ¬ Processing YouTube: {url}")
            yt = YouTubeSummarizer("exports")
            result, success = yt.process_video(url)
            if success:
                print(f"âœ… Saved to: {result}")
            else:
                print(f"âŒ Error: {result}")
        else:
            print(f"\nðŸŒ Scraping Web: {url}")
            ws = WebScraper("exports")
            result, success = ws.scrape_and_save(url)
            if success:
                print(f"âœ… Saved to: {result}")
            else:
                print(f"âŒ Error: {result}")
    else:
        print("\nðŸ’¡ Usage:")
        print("  python web_tools.py <url>")
        print("\nExamples:")
        print("  python web_tools.py https://example.com")
        print("  python web_tools.py https://www.youtube.com/watch?v=dQw4w9WgXcQ")
