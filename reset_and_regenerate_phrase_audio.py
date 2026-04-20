from flask import request, jsonify
import os
import zipfile
import tempfile

@app.route("/admin/upload-audio-zip", methods=["POST"])
def upload_audio_zip():
    key = request.args.get("key", "")
    expected_key = os.getenv("AUDIO_ZIP_UPLOAD_KEY", "123")

    if key != expected_key:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "missing file field"}), 400

    uploaded = request.files["file"]
    if not uploaded or not uploaded.filename:
        return jsonify({"ok": False, "error": "empty upload"}), 400

    upload_dir = os.path.abspath((os.getenv("UPLOAD_FOLDER") or "").strip() or "/data/uploads")
    os.makedirs(upload_dir, exist_ok=True)

    extracted = 0
    skipped_existing = 0
    failed = 0
    sample_failures = []

    fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    try:
        uploaded.save(tmp_zip)

        with zipfile.ZipFile(tmp_zip, "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue

                base_name = os.path.basename(member.filename)
                if not base_name:
                    continue

                # bare audiofiler
                ext = os.path.splitext(base_name)[1].lower()
                if ext not in {".mp3", ".wav", ".ogg", ".m4a", ".webm"}:
                    continue

                dst_abs = os.path.join(upload_dir, base_name)

                try:
                    if os.path.exists(dst_abs):
                        skipped_existing += 1
                        continue

                    with zf.open(member, "r") as src, open(dst_abs, "wb") as dst:
                        dst.write(src.read())

                    extracted += 1
                except Exception as e:
                    failed += 1
                    if len(sample_failures) < 10:
                        sample_failures.append({
                            "file": base_name,
                            "error": str(e),
                        })

        return jsonify({
            "ok": True,
            "target_dir": upload_dir,
            "extracted": extracted,
            "skipped_existing": skipped_existing,
            "failed": failed,
            "sample_failures": sample_failures,
        })

    except zipfile.BadZipFile:
        return jsonify({"ok": False, "error": "bad zip file"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        try:
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)
        except Exception:
            pass