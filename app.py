import os
import logging
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from threading import Lock
import time

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Lock para evitar múltiples requests simultáneos
request_lock = Lock()

# Inicializar Playwright globalmente
playwright_instance = None
browser_instance = None
browser_context = None

def get_browser_and_context():
    """Obtiene o crea la instancia del browser Y contexto (reutilizable)"""
    global playwright_instance, browser_instance, browser_context
    
    if browser_instance is None or not browser_instance.is_connected():
        logger.info("🚀 Iniciando browser...")
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
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
                "--disable-translate",
                "--hide-scrollbars",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-first-run",
                "--safebrowsing-disable-auto-update",
                "--disable-client-side-phishing-detection",
                "--disable-component-update",
                "--disable-hang-monitor"
            ]
        )
        
        # Crear contexto persistente
        browser_context = browser_instance.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="es-CO",
            viewport={"width": 1280, "height": 720},
            java_script_enabled=True,
            ignore_https_errors=True  # Ignorar errores SSL
        )
        
        # Timeout por defecto más corto
        browser_context.set_default_timeout(35000)
        logger.info("✅ Browser y contexto listos")
    
    return browser_instance, browser_context

# Pre-calentar al iniciar
try:
    logger.info("🔥 Pre-calentando browser...")
    get_browser_and_context()
except Exception as e:
    logger.error(f"❌ Error pre-calentando: {e}")

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud"""
    try:
        browser_status = "connected" if browser_instance and browser_instance.is_connected() else "disconnected"
        return jsonify({
            "status": "healthy",
            "browser": browser_status,
            "timestamp": time.time()
        }), 200
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500

@app.route('/consulta_cedula', methods=['POST'])
def consulta_cedula_api():
    start_time = time.time()
    
    # Lock para una consulta a la vez
    if not request_lock.acquire(blocking=False):
        return jsonify({
            "status": "error",
            "mensaje": "Otra consulta en proceso. Intenta en 10 segundos."
        }), 429
    
    page = None
    
    try:
        # Validar request
        data = request.json
        if not data:
            return jsonify({"status": "error", "mensaje": "No se envió JSON"}), 400
            
        cedula = data.get('cedula')
        if not cedula:
            return jsonify({"status": "error", "mensaje": "Falta la cédula"}), 400
        
        cedula_str = str(cedula).strip()
        if not cedula_str.isdigit():
            return jsonify({"status": "error", "mensaje": "La cédula debe ser numérica"}), 400
        
        logger.info(f"📋 Consultando cédula: {cedula_str}")
        
        # Obtener browser y contexto
        browser, context = get_browser_and_context()
        
        # Crear página
        page = context.new_page()
        
        # Bloquear recursos innecesarios para acelerar carga
        page.route("**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf}", lambda route: route.abort())
        
        logger.info("🌐 Navegando a Registraduría...")
        
        # ESTRATEGIA 1: Intentar carga rápida (25 segundos)
        try:
            page.goto(
                "https://wsp.registraduria.gov.co/censo/consultar.php",
                wait_until="domcontentloaded",
                timeout=25000
            )
            logger.info("✅ Carga rápida exitosa")
        except PlaywrightTimeoutError:
            logger.warning("⚠️ Timeout en carga inicial, intentando estrategia alternativa...")
            
            # ESTRATEGIA 2: Cargar sin esperar a que termine
            try:
                page.goto(
                    "https://wsp.registraduria.gov.co/censo/consultar.php",
                    wait_until="commit",  # Solo espera a que empiece a cargar
                    timeout=15000
                )
            except:
                pass
        
        # Esperar el formulario (lo importante)
        try:
            page.wait_for_selector('input[name="numdoc"]', state="visible", timeout=10000)
        except PlaywrightTimeoutError:
            logger.error("❌ Formulario no apareció")
            return jsonify({
                "status": "error",
                "mensaje": "La página de la Registraduría no cargó correctamente",
                "error_type": "form_not_found"
            }), 503
        
        # Llenar formulario
        logger.info("✍️ Llenando formulario...")
        page.fill('input[name="numdoc"]', cedula_str)
        
        # Enviar formulario
        logger.info("📤 Enviando formulario...")
        submit_start = time.time()
        
        try:
            # Intentar con navegación (30 segundos máximo)
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                page.click('input[type="submit"]')
        except PlaywrightTimeoutError:
            logger.warning("⚠️ Timeout en submit, verificando si hay respuesta...")
            # Esperar un poco más por si acaso
            page.wait_for_timeout(3000)
        
        submit_time = time.time() - submit_start
        logger.info(f"⏱️ Submit tomó {submit_time:.2f}s")
        
        # Pequeña espera adicional
        page.wait_for_timeout(2000)
        
        # Obtener contenido
        try:
            html = page.content()
            texto = page.inner_text("body")
        except Exception as e:
            logger.error(f"Error obteniendo contenido: {e}")
            html = ""
            texto = ""
        
        total_time = time.time() - start_time
        logger.info(f"✅ Proceso completo en {total_time:.2f}s")
        
        # Análisis de respuesta
        texto_lower = texto.lower()
        html_lower = html.lower()
        
        # CAPTCHA
        if "captcha" in html_lower or "robot" in html_lower or "recaptcha" in html_lower:
            logger.warning("🤖 CAPTCHA detectado")
            return jsonify({
                "status": "captcha",
                "mensaje": "CAPTCHA detectado. La Registraduría requiere verificación manual.",
                "cedula": cedula_str,
                "tiempo_proceso": round(total_time, 2)
            }), 200
        
        # No encontrado
        if "no se encontr" in texto_lower or "no existe" in texto_lower or "no hay" in texto_lower:
            logger.info("❌ Cédula no encontrada")
            return jsonify({
                "status": "not_found",
                "mensaje": "No se encontró información para esta cédula",
                "cedula": cedula_str,
                "tiempo_proceso": round(total_time, 2)
            }), 200
        
        # Verificar si hay contenido útil
        if len(texto.strip()) < 50:
            logger.warning("⚠️ Respuesta muy corta o vacía")
            return jsonify({
                "status": "error",
                "mensaje": "La página respondió pero sin información clara",
                "texto_obtenido": texto[:200],
                "tiempo_proceso": round(total_time, 2)
            }), 500
        
        # Éxito
        return jsonify({
            "status": "success",
            "cedula": cedula_str,
            "resultado_bruto": texto,
            "html_preview": html[:500],
            "tiempo_proceso": round(total_time, 2)
        }), 200
        
    except PlaywrightTimeoutError as e:
        total_time = time.time() - start_time
        logger.error(f"⏱️ Timeout después de {total_time:.2f}s: {str(e)}")
        return jsonify({
            "status": "error",
            "mensaje": "La Registraduría está muy lenta. Intenta nuevamente en 1 minuto.",
            "error_type": "timeout",
            "tiempo_transcurrido": round(total_time, 2)
        }), 504
        
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"💥 Error después de {total_time:.2f}s: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "mensaje": "Error inesperado",
            "error_type": "server_error",
            "error_detail": str(e),
            "tiempo_transcurrido": round(total_time, 2)
        }), 500
        
    finally:
        request_lock.release()
        if page:
            try:
                page.close()
            except:
                pass

@app.route('/', methods=['GET'])
def index():
    """Endpoint raíz"""
    return jsonify({
        "servicio": "Consulta Registraduría Colombia",
        "version": "2.0 - Optimizado",
        "endpoints": {
            "health": "/health (GET)",
            "consulta": "/consulta_cedula (POST)"
        },
        "ejemplo": {
            "method": "POST",
            "url": "/consulta_cedula",
            "body": {"cedula": "123456789"}
        },
        "notas": [
            "Timeout máximo: 90 segundos",
            "Respuesta esperada: 30-60 segundos",
            "Si falla, esperar 1 minuto antes de reintentar"
        ]
    })

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=10000)
