import subprocess
import os
import sys
import json
import time
import atexit
import urllib.request
import urllib.error

# Fix biar emoji/print gak crash di console Windows (cp1252)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ===== PATH =====
LLAMA_SERVER_EXE = r"C:\sagi_ai\llama.cpp\build\bin\Release\llama-server.exe"
MODEL = r"C:\sagi_ai\llama.cpp\models\qwen.gguf"

SPEAKER = r"C:\sagi_ai\audio\speaker.wav"
OUTPUT = r"C:\sagi_ai\audio\output.wav"

# ===== SERVER CONFIG =====
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

SERVER_START_TIMEOUT = 180   # detik: batas nunggu server siap saat pertama kali load model
GENERATE_TIMEOUT = 120       # detik: batas nunggu satu kali generate jawaban (model udah loaded, jadi harusnya cepat)

_server_process = None


# ===== SERVER LIFECYCLE =====
def start_llama_server():
    """Jalankan llama-server SEKALI di background. Model di-load sekali ini
    aja, gak perlu reload tiap kali user nanya -> jauh lebih cepat."""
    global _server_process

    if _server_process is not None and _server_process.poll() is None:
        return  # udah jalan, gak perlu start lagi

    if not os.path.exists(LLAMA_SERVER_EXE):
        print(f"❌ llama-server.exe tidak ditemukan di: {LLAMA_SERVER_EXE}")
        print("   Cek folder yang sama dengan llama-cli.exe, biasanya satu paket.")
        sys.exit(1)

    cmd = [
        LLAMA_SERVER_EXE,
        "-m", MODEL,
        "-c", "2048",
        "--host", SERVER_HOST,
        "--port", str(SERVER_PORT),
    ]

    # Windows-only: console terpisah & disembunyikan, biar kalau server ini
    # exit/crash gak ikut ngerusak console punya Python (pelajaran dari
    # masalah llama-cli sebelumnya).
    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_CONSOLE
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE

    print("🚀 [Server] Menjalankan llama-server & loading model (cuma sekali ini aja)...")
    print("⏳ [Server] Ini bisa makan waktu agak lama tergantung ukuran model, ditunggu ya...")

    _server_process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        startupinfo=startupinfo
    )

    # Polling sampai server siap nerima request
    deadline = time.time() + SERVER_START_TIMEOUT
    while time.time() < deadline:
        if _server_process.poll() is not None:
            print("❌ [Server] Proses server mati sebelum siap. Cek path LLAMA_SERVER_EXE / MODEL, atau port 8080 udah dipakai proses lain.")
            sys.exit(1)

        try:
            req = urllib.request.Request(f"{SERVER_URL}/health")
            urllib.request.urlopen(req, timeout=2)
            print("✅ [Server] llama-server siap dipakai!\n")
            return
        except urllib.error.HTTPError:
            # Dapat response (walau statusnya error) = server-nya udah hidup
            print("✅ [Server] llama-server siap dipakai!\n")
            return
        except Exception:
            time.sleep(1)

    print(f"⚠️ [Server] Server belum kasih respons setelah {SERVER_START_TIMEOUT}s, lanjut coba aja...")


def stop_llama_server():
    global _server_process
    if _server_process is not None and _server_process.poll() is None:
        print("\n🛑 [Server] Mematikan llama-server...")
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_process.kill()
            _server_process.wait()


atexit.register(stop_llama_server)


# ===== PERSONA =====
# Kepribadian & batasan AI diatur terpisah di file persona.py
# (satu folder sama file ini) -- biar gampang di-edit tanpa ubek-ubek
# script utama.
from persona import SYSTEM_PROMPT


# ===== LLM =====
def ask_llm(user_text):
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.7,
        "max_tokens": 128,
        "stop": ["User:", "\nUser:"]
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{SERVER_URL}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=GENERATE_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            output = result["choices"][0]["message"]["content"].strip()

            if output:
                print(output)
            else:
                print("⚠️ LLM output kosong")
                return "..."

            return output

    except urllib.error.URLError as e:
        return f"❌ error koneksi ke llama-server (udah nyala belum?): {e}"
    except TimeoutError:
        return f"❌ error LLM: timeout setelah {GENERATE_TIMEOUT}s"
    except Exception as e:
        return f"❌ error LLM: {e}"


# ===== TTS =====
TTS_SERVER_URL = "http://127.0.0.1:8810"  # dots_tts_server.py
TTS_TIMEOUT = 300  # detik -- CPU-only, generate bisa lama


def text_to_speech(text):
    print("\n🔊 [TTS] Mulai...")

    if not text.strip() or text.strip() == "...":
        print("❌ [TTS] Skip: teks kosong")
        return

    if not os.path.exists(SPEAKER):
        print(f"❌ [TTS] speaker.wav tidak ditemukan: {SPEAKER}")
        return

    print("📝 [TTS] Text:", text[:100], "...")

    # Cek dulu server dots.tts udah nyala apa belum
    try:
        req = urllib.request.Request(f"{TTS_SERVER_URL}/health")
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        print("❌ [TTS] dots_tts_server.py belum jalan!")
        print("   Buka terminal BARU, jalankan: python dots_tts_server.py")
        print("   Biarkan tetap terbuka, baru coba nanya lagi di sini.")
        return

    payload = {
        "text": text,
        "speaker_wav": SPEAKER,
        "out_path": OUTPUT
        # "prompt_text": "isi transkrip persis dari speaker.wav di sini kalau ada"
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{TTS_SERVER_URL}/synthesize",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    print("⏳ [TTS] Generate suara... (CPU-only, dots.tts bisa 1-3+ menit, sabar ya)")

    try:
        with urllib.request.urlopen(req, timeout=TTS_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("status") == "ok":
                print(f"✅ [TTS] Audio berhasil dibuat: {result['out_path']}")
            else:
                print(f"❌ [TTS ERROR]: {result.get('message')}")

    except urllib.error.URLError as e:
        print(f"❌ [TTS] Gagal konek ke dots_tts_server: {e}")
    except TimeoutError:
        print(f"❌ [TTS] Timeout setelah {TTS_TIMEOUT}s")
    except Exception as e:
        print(f"❌ [TTS EXCEPTION]: {e}")


# ===== MAIN LOOP =====
if __name__ == "__main__":
    start_llama_server()  # load model sekali di awal

    while True:
        try:
            user_input = input("\nKamu: ")

            if user_input.lower() in ["exit", "quit"]:
                print("👋 Bye!")
                break

            prompt = user_input  # role & persona udah diatur di SYSTEM_PROMPT

            print("\n🤖 AI:")
            response = ask_llm(prompt)

            print("\n📦 Response:", response)

            text_to_speech(response)

            print("🔁 Siap input lagi\n")

        except KeyboardInterrupt:
            print("\n👋 Ctrl+C ditekan, keluar...")
            break