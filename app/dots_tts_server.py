"""
=====================================================================
DOTS.TTS SERVER - TTS lokal, support Bahasa Indonesia native
=====================================================================
PERINGATAN: dots.tts didesain buat GPU. Di CPU-only (kayak setup kamu),
generate bisa 8-30x lebih lambat dari real-time -- artinya beberapa
detik audio bisa makan waktu 1-3+ menit. Ini pilihan kamu sendiri
setelah tau resikonya, jadi kita lanjut aja.

CARA INSTALL (jalankan di CMD/PowerShell):
    python -m pip install "git+https://github.com/rednote-hilab/dots.tts.git" -c "https://raw.githubusercontent.com/rednote-hilab/dots.tts/main/constraints/recommended.txt"

Kalau ada error soal versi Python, coba pastikan pakai Python 3.10 atau 3.11.

CARA JALANIN (biarkan window ini tetap terbuka selama chatbot dipakai):
    python dots_tts_server.py

Loading model pertama kali bisa makan waktu beberapa menit (2B
parameter, download checkpoint dari HuggingFace kalau belum ada +
loading ke RAM CPU).
=====================================================================
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = 8810

# Ganti ke "rednote-hilab/dots.tts-mf" kalau mau versi lebih cepat
# (MeanFlow, dikorbankan dikit kualitasnya demi kecepatan -- cocok
# buat CPU-only karena butuh lebih sedikit langkah proses)
MODEL_NAME = "rednote-hilab/dots.tts-mf"
NUM_STEPS = 4  # 4 = disarankan buat model -mf; kalau pakai -soar, pakai 10

print("🚀 [dots.tts] Loading model ke RAM (CPU)... ini BISA LAMA (beberapa menit), ditunggu ya.")

from dots_tts.runtime import DotsTtsRuntime
import soundfile as sf

runtime = DotsTtsRuntime.from_pretrained(
    MODEL_NAME,
    precision="float32",  # CPU lebih stabil pakai float32 drpd bfloat16
    optimize=False,        # torch.compile acceleration itu buat GPU, matiin di CPU
)

print(f"✅ [dots.tts] Model '{MODEL_NAME}' siap! Server nyala di http://{HOST}:{PORT}")
print("   Biarkan window ini tetap terbuka selama chatbot dipakai.")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # biar log HTTP bawaan gak berisik

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/synthesize":
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            text = body["text"]
            speaker_wav = body["speaker_wav"]
            out_path = body["out_path"]
            # Opsional: transkrip persis dari speaker_wav. Kalau kamu isi ini
            # dengan teks yang BENAR2 sesuai ucapan di speaker.wav, hasil
            # cloning-nya jauh lebih akurat. Kalau kosong, dipakai mode
            # "x-vector-only" (lebih gampang tapi sedikit kurang mirip).
            prompt_text = body.get("prompt_text", None)

            print(f"📝 [dots.tts] Generate: {text[:80]}...")
            print("⏳ [dots.tts] CPU-only, sabar ya, bisa 1-3+ menit...")

            gen_kwargs = dict(
                text=text,
                prompt_audio_path=speaker_wav,
                num_steps=NUM_STEPS,
                language="auto_detect",
            )
            if prompt_text:
                gen_kwargs["prompt_text"] = prompt_text

            result = runtime.generate(**gen_kwargs)

            audio = result["audio"].float().cpu().squeeze().numpy()
            sf.write(out_path, audio, 48000)

            print(f"✅ [dots.tts] Selesai, disimpan di: {out_path}")

            resp = json.dumps({"status": "ok", "out_path": out_path}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp)

        except Exception as e:
            print(f"❌ [dots.tts] Error: {e}")
            resp = json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp)


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), Handler)
    server.serve_forever()