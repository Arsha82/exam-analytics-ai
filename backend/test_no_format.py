import asyncio
import time
import httpx
import json

async def test():
    prompt = """You are an expert exam paper archivist.
Analyze these page previews of an examination document to detect if it contains a single paper or multiple merged exam papers:

--- Page 1 ---
# B.TECH DEGREE EXAMINATION - NOVEMBER 2021
Subject: Data Structures (CS-301)
Time: 3 Hours | Max Marks: 50
1. (a) Define Big-O notation. [2 Marks]

--- Page 3 ---
# B.TECH DEGREE EXAMINATION - MAY 2022
Subject: Data Structures (CS-301)
Time: 3 Hours | Max Marks: 50
1. (a) What is a circular queue? [2 Marks]

Respond ONLY with a JSON object:
{
  "is_merged_collection": true,
  "explanation": "...",
  "papers": [
    {"start_page": 1, "end_page": 2, "year": 2021, "session_month": "November", "total_marks": 50},
    {"start_page": 3, "end_page": 4, "year": 2022, "session_month": "May", "total_marks": 50}
  ]
}
"""
    print("Testing direct generation without 'format: json'...")
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post("http://localhost:11434/api/generate", json={
            "model": "gemma4:12b",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1}
        })
        elapsed = time.time() - t0
        print(f"Status: {r.status_code} in {elapsed:.1f}s")
        resp = r.json().get("response", "")
        print("Response preview:")
        print(resp[:400])

if __name__ == "__main__":
    asyncio.run(test())
