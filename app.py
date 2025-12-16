import os
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

playwright = sync_playwright().start()
browser = playwright.chromium.launch(
    headless=True,
    args=[
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-blink-features=AutomationControlled",
    ]
)

@app.route('/consulta_cedula', methods=['POST'])
def consulta_cedula_api():
    try:
        data = request.json
        cedula = data.get('cedula')

        if not cedula:
            return jsonify({"status": "error", "mensaje": "Falta la cédula"}), 400

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="es-CO"
        )

        page = context.new_page()
        page.goto(
            "https://wsp.registraduria.gov.co/censo/consultar.php",
            timeout=60000
        )

        # Llenar formulario
        page.fill('input[name="numdoc"]', str(cedula))
        page.click('input[type="submit"]')

        page.wait_for_timeout(5000)

        html = page.content()
        texto = page.inner_text("body")

        context.close()

        # 🛑 Detección simple de CAPTCHA
        if "captcha" in html.lower() or "robot" in html.lower():
            return jsonify({
                "status": "captcha",
                "mensaje": "CAPTCHA detectado"
            }), 429

        return jsonify({
            "status": "success",
            "cedula": cedula,
            "resultado_bruto": texto
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "error_log": str(e)
        }), 500

