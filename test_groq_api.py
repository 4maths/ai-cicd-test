#!/usr/bin/env python3
"""
Test script demo - Groq API
"""
import os
import sys
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Add scripts folder to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from ai_engine import call_llm, sanitize_data

def test_groq_connection():
    """Test basic Groq API connection"""
    print("=" * 60)
    print("Test Groq API Connection")
    print("=" * 60)
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY chưa được setting trong .env")
        return False
    
    print(f"✓ GROQ_API_KEY found (length: {len(api_key)})")
    print(f"✓ LLM_MODEL: {os.getenv('LLM_MODEL', 'llama-3.1-70b-versatile')}")
    print()
    
    # Test prompt đơn giản
    test_prompt = "Hello! Please respond with just 'OK' in one word."
    print(f"Sending test prompt: '{test_prompt}'")
    print()
    
    result = call_llm(test_prompt, max_tokens=50)
    
    if result:
        print("✓ API Response received!")
        print(f"Response: {result}")
        print()
        return True
    else:
        print("❌ Failed to get response from Groq API")
        return False


def test_sanitize_data():
    """Test data sanitization function"""
    print("=" * 60)
    print("Test Data Sanitization")
    print("=" * 60)
    
    test_data = """
    Error on 192.168.1.1
    Contact admin@example.com
    AWS key: AKIAIOSFODNN7EXAMPLE
    token=sk_live_abcdef123456
    """
    
    print("Original data:")
    print(test_data)
    print()
    
    sanitized = sanitize_data(test_data)
    print("Sanitized data:")
    print(sanitized)
    print()
    return True


if __name__ == "__main__":
    print("\n🚀 Testing Groq API Integration\n")
    
    # Test sanitization first
    test_sanitize_data()
    
    # Test API connection
    success = test_groq_connection()
    
    if success:
        print("\n✅ All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Tests failed")
        sys.exit(1)
