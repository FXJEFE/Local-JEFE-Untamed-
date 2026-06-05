
import sys
import os
import asyncio
from agent_v2 import EnhancedAgent

async def test_agent():
    print("Initializing EnhancedAgent...")
    agent = EnhancedAgent()
    
    print("\n--- Testing File Reading (UniversalFileHandler) ---")
    py_content = agent.read_file("random_test_script.py")
    print(f"Read random_test_script.py:\n{py_content}")
    
    csv_content = agent.read_file("random_data.csv")
    print(f"\nRead random_data.csv:\n{csv_content}")
    
    print("\n--- Testing RAG Indexing ---")
    # Index current directory with a small limit
    if agent.rag:
        stats_before = agent.rag.get_stats()
        print(f"Stats before: {stats_before}")
        
        # Explicitly index the new files
        # index_directory usually takes a path
        result = agent.rag.index_directory(".", max_files=10) 
        print(f"Indexing result: {result}")
        
        stats_after = agent.rag.get_stats()
        print(f"Stats after: {stats_after}")
        
        print("\n--- Testing RAG Search ---")
        question = "What is the content of random_test_script.py?"
        rag_answer = agent.ask_about_code(question)
        print(f"RAG Answer for '{question}':\n{rag_answer}")
        
        question2 = "What columns are in random_data.csv?"
        rag_answer2 = agent.ask_about_code(question2)
        print(f"RAG Answer for '{question2}':\n{rag_answer2}")
    else:
        print("Production RAG not available.")

if __name__ == "__main__":
    asyncio.run(test_agent())
