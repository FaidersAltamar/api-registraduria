import os
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

# Configuración básica
@app.route('/consulta_cedula', methods=['POST'])
def consulta_cedula_api():
    try:
        # 1. Recibimos la cédula
        data = request.json
        cedula = data.get('cedula')

        if not cedula:
            return jsonify({"status": "error", "mensaje": "Falta la cédula"}), 400

        # 2. Iniciamos el navegador virtual
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page()
            
            # 3. Vamos a la Registraduría
            page.goto("https://wsp.registraduria.gov.co/censo/consultar.php", timeout=60000)
            
            # 4. Llenamos el formulario
            # NOTA: Estos selectores pueden cambiar si la Registraduría actualiza su web.
            page.fill('input[name="numdoc"]', str(cedula))
            page.click('input[type="submit"]')
            
            # Esperamos un poco a que cargue
            page.wait_for_timeout(4000) 

            # 5. Extraemos TODO el texto de la página
            texto_visible = page.inner_text('body')

            browser.close()

            # 6. Devolvemos el resultado
            return jsonify({
                "status": "success",
                "cedula": cedula,
                "resultado_bruto": texto_visible
            })

    except Exception as e:
        return jsonify({"status": "error", "error_log": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
