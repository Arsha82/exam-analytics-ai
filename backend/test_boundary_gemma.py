import asyncio
import json
from app.services.ollama import ollama_service

page_previews = """
--- Page 1 ---
# B.TECH DEGREE EXAMINATION - NOVEMBER 2021
Subject: Data Structures (CS-301)
Time: 3 Hours | Max Marks: 50
SECTION A
1. (a) Define Big-O notation. [2 Marks]
(b) Explain linked list representation. [3 Marks]

--- Page 2 ---
SECTION B
3. Explain AVL tree insertion and rotation with an example. [10 Marks]
4. Write Dijkstra shortest path algorithm. [10 Marks]
[END OF PAPER]

--- Page 3 ---
# B.TECH DEGREE EXAMINATION - MAY 2022
Subject: Data Structures (CS-301)
Time: 3 Hours | Max Marks: 50
SECTION A
1. (a) What is a circular queue? [2 Marks]
(b) Differentiate between stack and queue. [3 Marks]

--- Page 4 ---
SECTION B
3. Explain Breadth First Search (BFS) and Depth First Search (DFS). [10 Marks]
4. Implement QuickSort algorithm. [10 Marks]
"""

prompt = f"""You are an expert exam paper archivist.
Analyze these page previews of an examination document to detect if it contains a single paper or multiple merged exam papers:

{page_previews}

Respond ONLY with valid JSON in this format:
{{
  "is_merged_collection": true,
  "explanation": "Human-readable reasoning explaining the split",
  "papers": [
    {{
      "start_page": 1,
      "end_page": 2,
      "year": 2021,
      "session_month": "November",
      "exam_type": "Regular",
      "subject": "Data Structures",
      "total_marks": 50,
      "confidence": 0.95
    }},
    {{
      "start_page": 3,
      "end_page": 4,
      "year": 2022,
      "session_month": "May",
      "exam_type": "Regular",
      "subject": "Data Structures",
      "total_marks": 50,
      "confidence": 0.95
    }}
  ]
}}"""

async def main():
    print("Testing Gemma 4 boundary detection...")
    res = await ollama_service.generate_json(
        prompt=prompt,
        model="gemma4:12b",
        temperature=0.1
    )
    print("Gemma 4 Response:")
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
