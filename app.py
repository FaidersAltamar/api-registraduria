import os
import logging
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Inicializar Playwright globalmente
playwright_instance = None
browser_instance = None

def get_browser():
    """Obtiene o crea la instancia del browser"""
    global playwright_instance, browser_instance
    
    if browser_instance is None or not browser_instance.is_connected():
        logger.info("Iniciando nuevo browser...")
        if playwright_instance is None:
            playwright_instance = sync_playwright().start()
        
        browser_instance = playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-blink-features=AutomationControlled",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )
    return browser_instance

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud para verificar que el servicio está funcionando"""
    return jsonify({"status": "healthy"}), 200

@app.route('/consulta_cedula', methods=['POST'])
def consulta_cedula_api():
    context = None
    page = None
    
    try:
        # Validar request
        data = request.json
        if not data:
            return jsonify({"status": "error", "mensaje": "No se envió JSON"}), 400
            
        cedula = data.get('cedula')
        if not cedula:
            return jsonify({"status": "error", "mensaje": "Falta la cédula"}), 400
        
        # Validar que la cédula sea numérica
        cedula_str = str(cedula).strip()
        if not cedula_str.isdigit():
            return jsonify({"status": "error", "mensaje": "La cédula debe ser numérica"}), 400
        
        logger.info(f"Consultando cédula: {cedula_str}")
        
        # Obtener browser
        browser = get_browser()
        
        # Crear contexto
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="es-CO",
            viewport={"width": 1920, "height": 1080}
        )
        
        page = context.new_page()
        
        # Navegar a la página
        logger.info("Navegando a la página de la Registraduría...")
        page.goto(
            "https://wsp.registraduria.gov.co/censo/consultar.php",
            wait_until="networkidle",
            timeout=60000
        )
        
        # Esperar a que el formulario esté visible
        page.wait_for_selector('input[name="numdoc"]', timeout=10000)
        
        # Llenar formulario
        logger.info("Llenando formulario...")
        page.fill('input[name="numdoc"]', cedula_str)
        
        # Click en submit y esperar navegación
        logger.info("Enviando formulario...")
        with page.expect_navigation(wait_until="networkidle", timeout=60000):
            page.click('input[type="submit"]')
        
        # Esperar a que cargue el contenido
        page.wait_for_timeout(3000)
        
        # Obtener contenido
        html = page.content()
        texto = page.inner_text("body")
        
        logger.info("Respuesta obtenida correctamente")
        
        # Detección de CAPTCHA o error
        texto_lower = texto.lower()
        html_lower = html.lower()
        
        if "captcha" in html_lower or "robot" in html_lower or "recaptcha" in html_lower:
            logger.warning("CAPTCHA detectado")
            return jsonify({
                "status": "captcha",
                "mensaje": "CAPTCHA detectado. La Registraduría requiere verificación manual."
            }), 429
        
        if "no se encontr" in texto_lower or "no existe" in texto_lower:
            logger.info("Cédula no encontrada")
            return jsonify({
                "status": "not_found",
                "mensaje": "No se encontró información para esta cédula",
                "cedula": cedula_str
            })
        
        # Respuesta exitosa
        return jsonify({
            "status": "success",
            "cedula": cedula_str,
            "resultado_bruto": texto,
            "html": html[:1000]  # Primeros 1000 caracteres del HTML
        })
        
    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout error: {str(e)}")
        return jsonify({
            "status": "error",
            "mensaje": "Timeout al consultar la página",
            "error_log": str(e)
        }), 504
        
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}")
        return jsonify({
            "status": "error",
            "mensaje": "Error interno del servidor",
            "error_log": str(e)
        }), 500
        
    finally:
        # Limpiar recursos
        if page:
            try:
                page.close()
            except:
                pass
        if context:
            try:
                context.close()
            except:
                pass

@app.route('/', methods=['GET'])
def index():
    """Endpoint raíz con información de uso"""
    return jsonify({
        "servicio": "Consulta Registraduría",
        "endpoint": "/consulta_cedula",
        "metodo": "POST",
        "body": {"cedula": "123456789"}
    })

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=10000)
