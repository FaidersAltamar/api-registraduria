"""
Worker de consulta Registraduría - Lugar de votación
Usa API directa de infovotantes (sin Playwright).

Variables de entorno (o archivo .env):
- TWOCAPTCHA_API_KEY: API key de 2Captcha
- CONSULTA_API_TOKEN: Token para Supabase/Lovable Cloud

Ejecutar: python main.py
"""

import os

# Cargar .env desde el directorio del script
try:
    from dotenv import load_dotenv
    _dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(_dir, '.env'))
    if not os.getenv('TWOCAPTCHA_API_KEY'):
        load_dotenv(os.path.join(_dir, '.env.example'))
except ImportError:
    pass

import sys
import time
import random
import logging
import json
import signal
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List

# Configuración
TWOCAPTCHA_API_KEY = os.getenv('TWOCAPTCHA_API_KEY')
CONSULTA_API_TOKEN = os.getenv('CONSULTA_API_TOKEN', 'FaidersAltamartokenelectoral123')
SUPABASE_FUNCTIONS_URL = "https://lsdnopjulddzkkboarsp.supabase.co/functions/v1"

API_URL = "https://apiweb-eleccionescolombia.infovotantes.com/api/v1/citizen/get-information"
BASE_URL = "https://eleccionescolombia.registraduria.gov.co/identificacion"
SITE_KEY = "6Lc9DmgrAAAAAJAjWVhjDy1KSgqzqJikY5z7I9SV"

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

MAX_WORKERS = 3

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _parse_2captcha_json(resp: requests.Response) -> Optional[Dict]:
    """Parsea JSON de 2Captcha manejando respuestas mal formadas."""
    if resp.status_code != 200:
        logger.warning(f"2Captcha HTTP {resp.status_code}: {resp.text[:100]}")
        return None
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        logger.warning(f"2Captcha JSON invalido: {e}. Raw: {resp.text[:200]}")
        # Intentar extraer primer objeto JSON si hay multiples concatenados
        text = resp.text.strip()
        depth = 0
        start = -1
        for i, c in enumerate(text):
            if c == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        pass
        return None


def solve_recaptcha(site_key: str, page_url: str) -> Optional[str]:
    """Resuelve reCAPTCHA v2 usando 2Captcha"""
    if not TWOCAPTCHA_API_KEY:
        logger.error("TWOCAPTCHA_API_KEY no configurado")
        return None

    try:
        resp = requests.post('http://2captcha.com/in.php', data={
            'key': TWOCAPTCHA_API_KEY,
            'method': 'userrecaptcha',
            'googlekey': site_key,
            'pageurl': page_url,
            'json': 1
        }, timeout=10)

        r = _parse_2captcha_json(resp)
        if r is None:
            return None
        if r.get('status') != 1:
            logger.error(f"Error 2Captcha: {r}")
            return None

        captcha_id = r.get('request')
        logger.info(f"CAPTCHA enviado, ID: {captcha_id}")

        for attempt in range(50):
            time.sleep(1.5 if attempt < 10 else 2)
            resp = requests.get('http://2captcha.com/res.php', params={
                'key': TWOCAPTCHA_API_KEY,
                'action': 'get', 'id': captcha_id, 'json': 1
            }, timeout=10)
            r = _parse_2captcha_json(resp)
            if r is None:
                continue  # reintentar en siguiente iteracion
            if r.get('status') == 1:
                logger.info(f"CAPTCHA resuelto (intento {attempt + 1})")
                return r.get('request')
            if r.get('request') != 'CAPCHA_NOT_READY':
                logger.error(f"Error: {r}")
                return None

        logger.error("Timeout CAPTCHA")
        return None
    except Exception as e:
        logger.error(f"Error solve_recaptcha: {e}")
        return None


def query_registraduria(cedula: str) -> Optional[Dict[str, Any]]:
    """Consulta lugar de votación vía API directa"""
    try:
        logger.info(f"Consultando Registraduria para cedula: {cedula}")
        token = solve_recaptcha(SITE_KEY, BASE_URL)
        if not token:
            return None

        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Origin': 'https://eleccionescolombia.registraduria.gov.co',
            'Referer': 'https://eleccionescolombia.registraduria.gov.co/',
            'Authorization': f'Bearer {token}',
        }
        payload = {
            "identification": str(cedula),
            "identification_type": "CC",
            "election_code": "congreso",
            "module": "polling_place",
            "platform": "web"
        }

        # Retry: 404 una vez (10s), 403 hasta 2 veces (10s, 20s), 500 hasta 2 veces (10s, 15s)
        resp = None
        for intento in range(3):
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                break
            if resp.status_code == 404 and intento == 0:
                logger.warning("API 404, reintentando en 10s...")
                time.sleep(10)
                continue
            if resp.status_code == 403 and intento < 2:
                delay = 10 * (2 ** intento)  # 10s, 20s
                logger.warning(f"API 403, reintentando en {delay}s...")
                time.sleep(delay)
                continue
            if resp.status_code == 500 and intento < 2:
                delay = 10 + (5 * intento)  # 10s, 15s
                logger.warning(f"API 500, reintentando en {delay}s...")
                time.sleep(delay)
                continue
            resp.raise_for_status()

        data = resp.json()

        if data.get('status') is False and data.get('status_code') == 13:
            return {"status": "not_found"}

        if not data.get('status') or not data.get('data'):
            return None

        inner = data.get('data', {})
        voter = inner.get('voter', {})
        polling_place = inner.get('polling_place', {})
        place_address = polling_place.get('place_address', {}) or {}

        if not inner.get('is_in_census', True) and inner.get('novelty'):
            nov = inner['novelty'][0]
            return {
                "nuip": str(voter.get('identification', '')),
                "departamento": "NO HABILITADA",
                "municipio": "NO HABILITADA",
                "puesto": nov.get('name', 'NO HABILITADA'),
                "direccion": "NO HABILITADA",
                "mesa": "0",
                "zona": "",
            }

        return {
            "nuip": str(voter.get('identification', cedula)),
            "departamento": place_address.get('state') or '',
            "municipio": place_address.get('town') or '',
            "puesto": polling_place.get('stand') or '',
            "direccion": place_address.get('address') or '',
            "mesa": str(polling_place.get('table', '')),
            "zona": str(place_address.get('zone', '')),
        }
    except requests.RequestException as e:
        logger.error(f"Error API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            code = e.response.status_code
            if code == 404:
                return {"status": "api_error", "error": "API no disponible (404)"}
            if code == 403:
                return {"status": "api_error", "error": "API no disponible (403 Forbidden)"}
            if code == 500:
                return {"status": "api_error", "error": "API no disponible (500)"}
        return {"status": "api_error", "error": str(e)}
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return None


def obtener_consultas_pendientes(tipo: str = 'registraduria', limit: int = 50) -> List[Dict]:
    """Obtiene cedulas pendientes de consultar"""
    try:
        resp = requests.get(
            f"{SUPABASE_FUNCTIONS_URL}/consultas-pendientes",
            params={'tipo': tipo, 'limit': limit},
            headers={'Authorization': f'Bearer {CONSULTA_API_TOKEN}'},
            timeout=30
        )
        if resp.status_code == 401:
            logger.error("Token invalido")
            return []
        resp.raise_for_status()
        return resp.json().get('consultas', [])
    except Exception as e:
        logger.error(f"Error obteniendo consultas: {e}")
        return []


def enviar_resultado(cola_id: str, cedula: str, exito: bool, datos: Optional[Dict] = None, error: Optional[str] = None) -> bool:
    """Envia resultado a Lovable Cloud"""
    try:
        resp = requests.post(
            f"{SUPABASE_FUNCTIONS_URL}/recibir-datos",
            json={
                'cola_id': cola_id, 'cedula': cedula, 'tipo': 'registraduria',
                'exito': exito, 'datos': datos, 'error': error
            },
            headers={'Authorization': f'Bearer {CONSULTA_API_TOKEN}', 'Content-Type': 'application/json'},
            timeout=30
        )
        if resp.status_code in (401, 404):
            logger.error(f"Error enviando: {resp.status_code}")
            return False
        resp.raise_for_status()
        return resp.json().get('success', False)
    except Exception as e:
        logger.error(f"Error enviando resultado: {e}")
        return False


def procesar_consulta(consulta: Dict) -> tuple:
    """Worker: consulta Registraduria. Retorna (consulta, resultado)."""
    time.sleep(random.uniform(0, 3))  # espaciar peticiones
    cedula = consulta['cedula']
    resultado = query_registraduria(cedula)
    return (consulta, resultado)


def main():
    """Loop principal: obtener pendientes -> consultar -> enviar"""
    if not TWOCAPTCHA_API_KEY:
        logger.error("Configura TWOCAPTCHA_API_KEY en variables de entorno")
        sys.exit(1)

    logger.info("Worker Registraduria iniciado")
    running = True

    def stop(sig, frame):
        nonlocal running
        running = False
        logger.info("Deteniendo...")

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while running:
        try:
            consultas = obtener_consultas_pendientes(tipo='registraduria', limit=5)

            if consultas:
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = {executor.submit(procesar_consulta, c): c for c in consultas}
                    for future in as_completed(futures):
                        if not running:
                            executor.shutdown(wait=False, cancel_futures=True)
                            break
                        try:
                            consulta, resultado = future.result()
                            cola_id = consulta['id']
                            cedula = consulta['cedula']
                            if resultado and resultado.get('status') == 'api_error':
                                enviar_resultado(cola_id, cedula, False, error=resultado.get('error', 'Error API'))
                            elif resultado and resultado.get('status') == 'not_found':
                                enviar_resultado(cola_id, cedula, False, error='Cedula no encontrada')
                            elif resultado and any(v for k, v in resultado.items() if k != 'status' and v):
                                datos = {
                                    'municipio_votacion': resultado.get('municipio'),
                                    'departamento_votacion': resultado.get('departamento'),
                                    'puesto_votacion': resultado.get('puesto'),
                                    'direccion_puesto': resultado.get('direccion'),
                                    'mesa': resultado.get('mesa'),
                                    'zona_votacion': resultado.get('zona'),
                                }
                                datos = {k: v for k, v in datos.items() if v is not None}
                                enviar_resultado(cola_id, cedula, True, datos=datos)
                            else:
                                enviar_resultado(cola_id, cedula, False, error='No se encontraron datos')
                        except Exception as e:
                            logger.error(f"Error procesando consulta: {e}")
                time.sleep(5)

            if not consultas:
                logger.info("Sin consultas. Esperando 30s...")
                time.sleep(30)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            time.sleep(10)

    logger.info("Worker finalizado")


if __name__ == "__main__":
    main()
