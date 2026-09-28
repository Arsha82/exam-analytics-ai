"""Test OCR pipeline: check models, test vision, test native PDF extraction."""
import httpx
import json
import base64
import sys
from pathlib import Path

BASE = "http://localhost:11434"

def check_models():
    print("=" * 60)
    print("1. INSTALLED OLLAMA MODELS")
    print("=" * 60)
    r = httpx.get(f"{BASE}/api/tags")
    for m in r.json().get("models", []):
        name = m["name"]
        size_gb = m.get("size", 0) / 1e9
        print(f"  {name:55s}  {size_gb:.1f} GB")
    print()

def test_text_generation():
    print("=" * 60)
    print("2. TEXT GENERATION (gemma4:12b)")
    print("=" * 60)
    try:
        r = httpx.post(
            f"{BASE}/api/generate",
            json={"model": "gemma4:12b", "prompt": "Say 'OCR test OK' in exactly 3 words.", "stream": False},
            timeout=60,
        )
        print(f"  Status: {r.status_code}")
        print(f"  Response: {r.json().get('response', '')[:200]}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

def test_embedding():
    print("=" * 60)
    print("3. EMBEDDING (nomic-embed-text)")
    print("=" * 60)
    try:
        r = httpx.post(
            f"{BASE}/api/embeddings",
            json={"model": "nomic-embed-text:latest", "prompt": "test embedding"},
            timeout=30,
        )
        emb = r.json().get("embedding", [])
        print(f"  Status: {r.status_code}")
        print(f"  Embedding dim: {len(emb)}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

def create_test_image():
    """Create a minimal test image with text using Pillow."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (600, 200), "white")
    draw = ImageDraw.Draw(img)
    # Use default font
    draw.text((30, 30), "Q1. Define Newton's Second Law of Motion. [5 marks]", fill="black")
    draw.text((30, 80), "Q2. Explain the concept of entropy in thermodynamics. [10 marks]", fill="black")
    draw.text((30, 130), "Q3. Derive the equation for simple harmonic motion. [8 marks]", fill="black")
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def test_vision_model(model_name, image_bytes):
    print(f"  Testing: {model_name}")
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    try:
        r = httpx.post(
            f"{BASE}/api/generate",
            json={
                "model": model_name,
                "prompt": "Extract all text from this image exactly as written.",
                "images": [b64],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=120,
        )
        print(f"    Status: {r.status_code}")
        if r.status_code == 200:
            text = r.json().get("response", "")
            print(f"    Extracted ({len(text)} chars): {text[:300]}")
            return True
        else:
            print(f"    Error body: {r.text[:300]}")
            return False
    except Exception as e:
        print(f"    EXCEPTION: {e}")
        return False

def test_vision():
    print("=" * 60)
    print("4. VISION OCR TESTS")
    print("=" * 60)
    
    image_bytes = create_test_image()
    print(f"  Test image: {len(image_bytes)} bytes")
    print()
    
    models_to_test = [
        "hf.co/sahilchachra/Unlimited-OCR-GGUF:Q4_K_M",
        "moondream:latest",
        "gemma4:12b",
    ]
    
    results = {}
    for model in models_to_test:
        ok = test_vision_model(model, image_bytes)
        results[model] = ok
        print()
    
    print("  SUMMARY:")
    for model, ok in results.items():
        status = "✅ WORKING" if ok else "❌ FAILED"
        print(f"    {model}: {status}")
    
    return results

def test_native_pdf_extraction():
    print("=" * 60)
    print("5. NATIVE PDF TEXT EXTRACTION (pypdfium2)")
    print("=" * 60)
    
    # Check if there are any uploaded PDFs
    upload_dir = Path("uploads")
    pdfs = list(upload_dir.glob("*.pdf")) if upload_dir.exists() else []
    
    if not pdfs:
        print("  No PDFs in uploads/ directory — creating test PDF...")
        # Create a minimal test PDF with reportlab or just test pypdfium2 import
        try:
            import pypdfium2 as pdfium
            print("  pypdfium2 imported OK")
        except Exception as e:
            print(f"  ERROR importing pypdfium2: {e}")
    else:
        import pypdfium2 as pdfium
        pdf_path = pdfs[0]
        print(f"  Testing with: {pdf_path.name}")
        pdf = pdfium.PdfDocument(str(pdf_path))
        print(f"  Pages: {len(pdf)}")
        for i, page in enumerate(pdf):
            if i >= 2:
                break
            text_page = page.get_textpage()
            text = text_page.get_text_range()
            has_text = bool(text and text.strip())
            print(f"  Page {i+1}: {'HAS native text' if has_text else 'NO native text (scanned)'} ({len(text or '')} chars)")
            if has_text:
                print(f"    Preview: {text[:200]}")
    print()

if __name__ == "__main__":
    check_models()
    test_text_generation()
    test_embedding()
    test_native_pdf_extraction()
    test_vision()
