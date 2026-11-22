import os
import json
import time
import urllib.request
import urllib.error
import telebot

BOT_TOKEN = (os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
GROQ_MODEL_ENV = (os.getenv("GROQ_MODEL") or "").strip()

MODELOS_RESPALDO = [
    m for m in dict.fromkeys([
        GROQ_MODEL_ENV,
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "qwen/qwen3-32b",
    ]) if m
]

if not BOT_TOKEN:
    raise RuntimeError("Falta BOT_TOKEN (o TELEGRAM_BOT_TOKEN) en Secrets.")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

historial_chats = {}
MAX_HISTORIAL = 10
MAX_TELEGRAM_LEN = 4000


def recortar_texto(texto: str) -> str:
    limpio = (texto or "").strip()
    if len(limpio) <= MAX_TELEGRAM_LEN:
        return limpio
    return limpio[: MAX_TELEGRAM_LEN - 25] + "\n\n[Mensaje recortado]"


def obtener_modelos_groq() -> list:
    modelos = []
    if GROQ_MODEL_ENV:
        modelos.append(GROQ_MODEL_ENV)

    if GROQ_API_KEY:
        try:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "User-Agent": "Mozilla/5.0",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            remotos = [
                item.get("id")
                for item in (data.get("data") or [])
                if isinstance(item, dict) and item.get("id")
            ]
            for modelo_id in remotos:
                if modelo_id not in modelos:
                    modelos.append(modelo_id)
        except Exception as e:
            print(f"[AVISO MODELOS GROQ] {e}")

    for m in MODELOS_RESPALDO:
        if m not in modelos:
            modelos.append(m)

    return modelos


def solicitar_groq(modelo: str, mensajes: list) -> str:
    payload = {
        "model": modelo,
        "messages": mensajes,
        "temperature": 0.7,
        "max_tokens": 700,
    }

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Groq devolvio una respuesta vacia.")

    contenido = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not contenido:
        raise RuntimeError("Groq devolvio texto vacio.")

    return contenido


def obtener_respuesta_ia(chat_id: int, prompt_usuario: str) -> str:
    if not GROQ_API_KEY:
        return "Falta configurar GROQ_API_KEY en Secrets."

    mensajes_previos = historial_chats.get(chat_id, [])
    mensajes = mensajes_previos + [{"role": "user", "content": prompt_usuario}]

    modelos_a_probar = obtener_modelos_groq()
    ultimo_error = None

    for modelo in modelos_a_probar:
        try:
            respuesta = solicitar_groq(modelo, mensajes)
            historial_chats[chat_id] = (mensajes + [{"role": "assistant", "content": respuesta}])[-MAX_HISTORIAL:]
            return recortar_texto(respuesta)
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", errors="ignore")
            ultimo_error = f"HTTP {e.code} ({modelo}): {detalle}"
            print(f"[GROQ FALLO] {ultimo_error}")
            if e.code in (400, 404):
                continue
            raise RuntimeError(ultimo_error)
        except Exception as e:
            ultimo_error = f"Error ({modelo}): {e}"
            print(f"[GROQ ERROR] {ultimo_error}")
            raise RuntimeError(ultimo_error)

    raise RuntimeError(ultimo_error or "Ningun modelo de Groq disponible respondio.")


def formatear_remitente(message) -> str:
    usuario = getattr(message, "from_user", None)
    if not usuario:
        return "@Gordofof"
    if usuario.username:
        return f"@{usuario.username}"
    nombre = " ".join(p for p in [usuario.first_name, usuario.last_name] if p).strip()
    return nombre or "@Gordofof"


def consultar_datos_bin(bin_code: str, remitente: str) -> str:
    url = f"https://lookup.binlist.net/{bin_code[:6]}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept-Version": "3",
            "User-Agent": "Mozilla/5.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return "Limite de consultas alcanzado en el servicio de BINs. Espera unos segundos y reintenta."
        return f"No se encontro informacion para el BIN {bin_code} (HTTP {e.code})."

    if status == 200:
        pais = (data.get("country") or {}).get("name") or "UNKNOWN"
        emoji = (data.get("country") or {}).get("emoji") or ""
        banco = ((data.get("bank") or {}).get("name") or "UNKNOWN").upper()
        marca_base = (data.get("scheme") or "").upper()
        nivel_raw = (data.get("brand") or "").upper()
        marca = f"{marca_base} {nivel_raw}".strip() if (marca_base and nivel_raw) else (marca_base or nivel_raw or "UNKNOWN")
        tipo = (data.get("type") or "UNKNOWN").upper()
        nivel = nivel_raw or "CLASSIC"

        return (
            f"🔍 BIN CHECKER\n\n"
            f"✅ Bin: {bin_code}\n"
            f"🌐 Country: {pais} {emoji}".strip() + "\n"
            f"🏦 Bank: {banco}\n"
            f"💳 Brand: {marca}\n"
            f"💲 Type: {tipo}\n"
            f"🏆 Level: {nivel}\n"
            f"👤 Sent by: {remitente}"
        )

    return f"No se encontro informacion para el BIN {bin_code}."


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    texto = (
        "¡Hola! 🍧 🎬 Soy **Wisky**, tu bot multifunción.\n\n"
        "📥 **Para recortar clips:**\n"
        "Envíame el **enlace directo** de YouTube, Facebook, Tik
