import logging
import time
import random
from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def crear_sesion():
    sesion = requests.Session()
    
    retry_strategy = Retry(
        total=2,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    sesion.mount("http://", adapter)
    sesion.mount("https://", adapter)
    
    user_agent = random.choice(USER_AGENTS)
    
    sesion.headers.update({
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-CO,es;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
    })
    
    return sesion

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "method": "HTTP Requests con Anti-Deteccion",
        "timestamp": time.time()
    }), 200

@app.route('/consulta_cedula', methods=['POST'])
def consulta_cedula_api():
    start_time = time.time()
    
    try:
        data = request.json
        if not data:
            return jsonify({
                "status": "error",
                "mensaje": "No se envio JSON en el body"
            }), 400
        
        cedula = data.get('cedula')
        if not cedula:
            return jsonify({
                "status": "error",
                "mensaje": "Falta el campo cedula en el JSON"
            }), 400
        
        cedula_str = str(cedula).strip()
        if not cedula_str.isdigit():
            return jsonify({
                "status": "error",
                "mensaje": "La cedula debe contener solo numeros"
            }), 400
        
        if len(cedula_str) < 6 or len(cedula_str) > 10:
            return jsonify({
                "status": "error",
                "mensaje": "La cedula debe tener entre 6 y 10 digitos"
            }), 400
        
        logger.info(f"Consultando cedula: {cedula_str}")
        
        sesion = crear_sesion()
        
        url_base = "https://wsp.registraduria.gov.co/censo/consultar"
        
        logger.info("Visitando pagina inicial...")
        
        time.sleep(random.uniform(1.0, 3.0))
        
        try:
            response_get = sesion.get(
                url_base,
                timeout=30,
                allow_redirects=True
            )
            response_get.raise_for_status()
            logger.info(f"GET exitoso - Status: {response_get.status_code}")
        except requests.Timeout:
            logger.error("Timeout al cargar el formulario")
            return jsonify({
                "status": "error",
                "mensaje": "Timeout al conectar con la Registraduria. Intenta en 1 minuto.",
                "error_type": "timeout_get"
            }), 504
        except requests.RequestException as e:
            logger.error(f"Error en GET: {e}")
            return jsonify({
                "status": "error",
                "mensaje": f"Error al conectar con la Registraduria: {str(e)}",
                "error_type": "connection_error"
            }), 503
        
        soup = BeautifulSoup(response_get.text, 'lxml')
        
        sesion.headers.update({
            'Referer': url_base,
            'Origin': 'https://wsp.registraduria.gov.co'
        })
        
        form_data = {
            'numdoc': cedula_str,
        }
        
        form = soup.find('form')
        if form:
            for hidden in form.find_all('input', type='hidden'):
                name = hidden.get('name')
                value = hidden.get('value', '')
                if name:
                    form_data[name] = value
                    logger.info(f"Campo oculto: {name}")
        
        action_url = url_base
        if form and form.get('action'):
            action = form.get('action')
            if action.startswith('http'):
                action_url = action
            else:
                action_url = f"https://wsp.registraduria.gov.co{action}" if action.startswith('/') else f"{url_base}/{action}"
        
        logger.info(f"Enviando a: {action_url}")
        
        time.sleep(random.uniform(2.0, 4.0))
        
        logger.info("Enviando consulta...")
        try:
            response_post = sesion.post(
                action_url,
                data=form_data,
                timeout=45,
                allow_redirects=True
            )
            response_post.raise_for_status()
            logger.info(f"POST exitoso - Status: {response_post.status_code}")
        except requests.Timeout:
            logger.error("Timeout al enviar consulta")
            return jsonify({
                "status": "error",
                "mensaje": "Timeout al procesar la consulta. La Registraduria esta lenta.",
                "error_type": "timeout_post"
            }), 504
        except requests.RequestException as e:
            logger.error(f"Error en POST: {e}")
            return jsonify({
                "status": "error",
                "mensaje": f"Error al enviar consulta: {str(e)}",
                "error_type": "post_error"
            }), 503
        
        soup_result = BeautifulSoup(response_post.text, 'lxml')
        texto_completo = soup_result.get_text(separator='\n', strip=True)
        
        total_time = time.time() - start_time
        logger.info(f"Respuesta obtenida en {total_time:.2f}s")
        
        texto_lower = texto_completo.lower()
        html_lower = response_post.text.lower()
        
        captcha_patterns = [
            'captcha', 'recaptcha', 'robot', 'verificacion', 
            'g-recaptcha', 'hcaptcha', 'cloudflare', 'challenge',
            'confirma que no eres un robot', 'verifica que eres humano'
        ]
        
        if any(pattern in html_lower for pattern in captcha_patterns):
            logger.warning("CAPTCHA detectado en HTML")
            
            return jsonify({
                "status": "captcha",
                "mensaje": "La Registraduria ha activado CAPTCHA. Requiere verificacion manual.",
                "cedula": cedula_str,
                "tiempo_proceso": round(total_time, 2),
                "sugerencia": "Espera 5-10 minutos antes de reintentar"
            }), 200
        
        not_found_patterns = [
            'no se encontro', 'no existe', 'no hay informacion',
            'no registra', 'no se encuentra', 'cedula no valida',
            'no hay registro', 'sin informacion', 'no aparece'
        ]
        
        if any(phrase in texto_lower for phrase in not_found_patterns):
            logger.info("Cedula no encontrada")
            return jsonify({
                "status": "not_found",
                "mensaje": "No se encontro informacion para esta cedula en el censo electoral",
                "cedula": cedula_str,
                "tiempo_proceso": round(total_time, 2)
            }), 200
        
        resultado = {
            "nombre": None,
            "cedula": cedula_str,
            "puesto_votacion": None,
            "direccion": None,
            "municipio": None,
            "departamento": None,
            "mesa": None,
            "lugar_votacion": None
        }
        
        try:
            tabla = soup_result.find('table')
            if tabla:
                rows = tabla.find_all('tr')
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        campo = cells[0].get_text(strip=True).lower()
                        valor = cells[1].get_text(strip=True)
                        
                        if 'nombre' in campo:
                            resultado['nombre'] = valor
                        elif 'puesto' in campo or 'votacion' in campo:
                            resultado['puesto_votacion'] = valor
                        elif 'direccion' in campo:
                            resultado['direccion'] = valor
                        elif 'municipio' in campo:
                            resultado['municipio'] = valor
                        elif 'departamento' in campo:
                            resultado['departamento'] = valor
                        elif 'mesa' in campo:
                            resultado['mesa'] = valor
                        elif 'lugar' in campo:
                            resultado['lugar_votacion'] = valor
            
            if not resultado['nombre']:
                for elem in soup_result.find_all(['div', 'p', 'span']):
                    texto_elem = elem.get_text(strip=True).lower()
                    if 'nombre' in texto_elem and ':' in texto_elem:
                        partes = texto_elem.split(':')
                        if len(partes) >= 2:
                            resultado['nombre'] = partes[1].strip().upper()
        
        except Exception as e:
            logger.warning(f"Error extrayendo datos: {e}")
        
        if len(texto_completo.strip()) < 50:
            logger.warning("Respuesta muy corta")
            return jsonify({
                "status": "error",
                "mensaje": "La pagina respondio pero sin informacion util",
                "error_type": "empty_response",
                "tiempo_proceso": round(total_time, 2)
            }), 500
        
        return jsonify({
            "status": "success",
            "cedula": cedula_str,
            "datos_estructurados": resultado,
            "resultado_bruto": texto_completo,
            "html_preview": response_post.text[:1000],
            "tiempo_proceso": round(total_time, 2),
            "url_consultada": action_url
        }), 200
        
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"Error inesperado: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "mensaje": "Error interno del servidor",
            "error_type": "server_error",
            "error_detail": str(e),
            "tiempo_transcurrido": round(total_time, 2)
        }), 500

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "servicio": "Consulta Registraduria Colombia",
        "version": "3.1 - Anti-Deteccion Mejorado",
        "mejoras": [
            "User Agents aleatorios",
            "Headers completos y realistas",
            "Delays humanos (1-4 segundos)",
            "Referer y Origin correctos",
            "Deteccion mejorada de CAPTCHA",
            "Parseo robusto de formularios"
        ],
        "endpoints": {
            "health": "GET /health",
            "consulta": "POST /consulta_cedula"
        },
        "ejemplo": {
            "method": "POST",
            "url": "/consulta_cedula",
            "headers": {"Content-Type": "application/json"},
            "body": {"cedula": "12345678"}
        }
    })

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=10000)
