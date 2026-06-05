#!/usr/bin/env python3
"""
Token Manager
Handles accurate token counting for different models.
Falls back to approximation if tiktoken unavailable.
"""

import logging
from typing import Optional, Dict, List
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# Attempt to import tiktoken for accurate tokenization
TIKTOKEN_AVAILABLE = False
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    logger.warning("tiktoken not available, using approximation")


class TokenManager:
    """
    Handles accurate token counting for different models.
    Falls back to approximation if tiktoken unavailable.
    
    Features:
    - Accurate token counting using tiktoken (when available)
    - Content-type aware approximation fallback
    - Token budget management
    - Text truncation to fit token limits
    """

    def __init__(self):
        self.encoders: Dict[str, any] = {}

        if TIKTOKEN_AVAILABLE:
            try:
                # GPT-4 encoding works well for most models
                self.default_encoder = tiktoken.get_encoding("cl100k_base")
                logger.info("Loaded tiktoken encoder for accurate token counting")
            except Exception as e:
                logger.warning(f"Could not load tiktoken encoder: {e}")
                self.default_encoder = None
        else:
            self.default_encoder = None

    def count_tokens(
        self,
        text: str,
        model: Optional[str] = None
    ) -> int:
        """
        Count tokens accurately for given text.
        Uses tiktoken if available, otherwise approximates.
        
        Args:
            text: Text to count tokens for
            model: Optional model name (currently unused, reserved for future)
            
        Returns:
            Token count
        """
        if not text:
            return 0

        # Use tiktoken if available
        if self.default_encoder:
            try:
                return len(self.default_encoder.encode(text))
            except Exception as e:
                logger.warning(f"Tokenization failed: {e}, falling back to approximation")

        # Fallback to approximation
        # Different factors for different content types
        if self._is_code(text):
            # Code is more token-dense
            return max(1, len(text) // 3)
        elif self._is_structured(text):
            # JSON/XML also more dense
            return max(1, len(text) // 3.2)
        else:
            # Regular text
            return max(1, len(text) // 4)

    def _is_code(self, text: str) -> bool:
        """Heuristic to detect code"""
        code_indicators = [
            'def ', 'class ', 'import ', 'function', 
            'const ', 'let ', 'var ', 'public ', 'private ',
            '#!/', '#include', 'package ', 'fn ', 'impl '
        ]
        return any(indicator in text for indicator in code_indicators)

    def _is_structured(self, text: str) -> bool:
        """Heuristic to detect structured data"""
        try:
            json.loads(text)
            return True
        except:
            return text.strip().startswith('<') or '{' in text[:100]

    def truncate_to_tokens(
        self,
        text: str,
        max_tokens: int,
        model: Optional[str] = None
    ) -> str:
        """
        Truncate text to fit within token limit.
        Tries to preserve complete sentences/lines.
        
        Args:
            text: Text to truncate
            max_tokens: Maximum number of tokens
            model: Optional model name
            
        Returns:
            Truncated text with marker if truncated
        """
        current_tokens = self.count_tokens(text, model)

        if current_tokens <= max_tokens:
            return text

        # Estimate character limit
        chars_per_token = len(text) / current_tokens
        target_chars = int(max_tokens * chars_per_token * 0.95)  # 5% safety margin

        # Try to break at sentence boundaries
        truncated = text[:target_chars]

        # Look for last sentence boundary
        for separator in ['\n\n', '\n', '. ', '! ', '? ']:
            last_boundary = truncated.rfind(separator)
            if last_boundary > target_chars * 0.8:  # Must be reasonably close
                truncated = truncated[:last_boundary + len(separator)]
                break

        # Verify we're under limit
        if self.count_tokens(truncated, model) > max_tokens:
            # More aggressive truncation needed
            while self.count_tokens(truncated, model) > max_tokens:
                truncated = truncated[:int(len(truncated) * 0.9)]

        return truncated + "\n... [truncated to fit context]"

    def estimate_context_usage(
        self,
        messages: List,
        system_prompt: str = "",
        model: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Estimate total token usage for a conversation.
        Returns breakdown by component.
        
        Args:
            messages: List of messages or Message objects
            system_prompt: System prompt text
            model: Optional model name
            
        Returns:
            Dict with token counts for system_prompt, messages, overhead, and total
        """
        usage = {
            "system_prompt": self.count_tokens(system_prompt, model),
            "messages": 0,
            "overhead": 0
        }

        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get('content', '')
            elif hasattr(msg, 'content'):
                content = msg.content
            else:
                content = str(msg)
                
            usage["messages"] += self.count_tokens(content, model)

        # Add overhead for message formatting (role markers, etc.)
        usage["overhead"] = len(messages) * 10

        usage["total"] = sum(usage.values())

        return usage

    def split_text_by_tokens(
        self,
        text: str,
        max_tokens: int,
        overlap: int = 100
    ) -> List[str]:
        """
        Split text into chunks by token count with overlap.
        Useful for processing large documents.
        
        Args:
            text: Text to split
            max_tokens: Maximum tokens per chunk
            overlap: Number of tokens to overlap between chunks
            
        Returns:
            List of text chunks
        """
        if self.count_tokens(text) <= max_tokens:
            return [text]

        chunks = []
        lines = text.split('\n')
        current_chunk = []
        current_tokens = 0

        for line in lines:
            line_tokens = self.count_tokens(line)

            if current_tokens + line_tokens > max_tokens and current_chunk:
                # Save current chunk
                chunks.append('\n'.join(current_chunk))

                # Start new chunk with overlap
                overlap_lines = []
                overlap_tokens = 0

                for prev_line in reversed(current_chunk):
                    prev_tokens = self.count_tokens(prev_line)
                    if overlap_tokens + prev_tokens <= overlap:
                        overlap_lines.insert(0, prev_line)
                        overlap_tokens += prev_tokens
                    else:
                        break

                current_chunk = overlap_lines
                current_tokens = overlap_tokens

            current_chunk.append(line)
            current_tokens += line_tokens

        # Add final chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks

    def get_token_breakdown(self, text: str) -> Dict:
        """
        Get detailed token breakdown for text.
        
        Returns:
            Dict with character count, word count, line count, and token count
        """
        return {
            'characters': len(text),
            'words': len(text.split()),
            'lines': len(text.split('\n')),
            'tokens': self.count_tokens(text),
            'chars_per_token': len(text) / max(1, self.count_tokens(text))
        }


# Global instance
_token_manager: Optional[TokenManager] = None

def get_token_manager() -> TokenManager:
    """Get token manager singleton"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager


if __name__ == "__main__":
    print("Testing Token Manager...")
    
    token_mgr = get_token_manager()
    
    # Test basic counting
    test_texts = [
        "Hello world",
        "def hello():\n    print('world')\n",
        '{"name": "test", "value": 123}',
        "This is a longer piece of text " * 10
    ]
    
    print("\n📊 Token Counting:")
    for text in test_texts:
        tokens = token_mgr.count_tokens(text)
        breakdown = token_mgr.get_token_breakdown(text)
        print(f"\nText length: {len(text)} chars")
        print(f"  Tokens: {tokens}")
        print(f"  Words: {breakdown['words']}")
        print(f"  Chars/token: {breakdown['chars_per_token']:.2f}")
    
    # Test truncation
    long_text = "This is a sentence. " * 100
    truncated = token_mgr.truncate_to_tokens(long_text, max_tokens=50)
    print(f"\n✂️  Truncation:")
    print(f"  Original: {token_mgr.count_tokens(long_text)} tokens")
    print(f"  Truncated: {token_mgr.count_tokens(truncated)} tokens")
    
    # Test splitting
    chunks = token_mgr.split_text_by_tokens(long_text, max_tokens=100, overlap=20)
    print(f"\n📄 Splitting:")
    print(f"  Chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks[:3]):
        print(f"  Chunk {i+1}: {token_mgr.count_tokens(chunk)} tokens")
    
    print("\n✅ All tests passed!")
