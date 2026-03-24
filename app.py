from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from database import init_db, get_db
import requests
import json
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "mailai_secret_key_2024"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODELO = "llama3"

EMAILS_DEMO = [
    {"sender_name": "Jose Vicente Carratalá", "sender_email": "josevcarra@empresa.com",
     "subject": "Error crítico en producción - URGENTE",
     "body": "Hola equipo,\n\nTenemos un fallo grave en el servidor de producción. Los clientes no pueden acceder al sistema desde hace 2 horas. Necesitamos una solución inmediata o perderemos contratos importantes.\n\nPor favor atended esto cuanto antes.\n\nJose Vicente",
     "time": "09:14"},
    {"sender_name": "Thais Esteve", "sender_email": "thais.esteve@ventas.com",
     "subject": "Propuesta comercial Q1 - revisión",
     "body": "Buenos días,\n\nAdjunto la propuesta comercial para el primer trimestre. Me gustaría que revisarais los precios y condiciones antes de enviarla al cliente.\n\nQuedo a vuestra disposición.\n\nThais Esteve\nDepartamento de Ventas",
     "time": "10:32"},
    {"sender_name": "Héctor López", "sender_email": "hector.lopez@rrhh.com",
     "subject": "Recordatorio: entrega de justificantes de vacaciones",
     "body": "Estimados compañeros,\n\nOs recordamos que el plazo para entregar los justificantes de vacaciones del mes pasado vence el próximo viernes.\n\nPor favor, enviáis la documentación al departamento de RRHH antes de esa fecha.\n\nGracias.\nHéctor López\nRRHH",
     "time": "11:05"},
    {"sender_name": "Thais Esteve", "sender_email": "thais.esteve@ventas.com",
     "subject": "Factura #2024-0892 pendiente de pago",
     "body": "Estimados,\n\nLe informamos que la factura número 2024-0892 por importe de 3.450€ correspondiente al servicio de mantenimiento de enero sigue pendiente de pago.\n\nLe rogamos que proceda al abono a la mayor brevedad posible para evitar recargos por demora.\n\nThais Esteve",
     "time": "Ayer"},
    {"sender_name": "Jose Vicente Carratalá", "sender_email": "josevcarra@empresa.com",
     "subject": "Consulta sobre plan de soporte técnico",
     "body": "Buenos días,\n\nSoy cliente desde hace 3 años y me gustaría saber si existe la posibilidad de ampliar mi plan de soporte actual al plan premium. ¿Cuáles son los beneficios y el coste?\n\nTambién quería preguntar si hay algún descuento para clientes fieles.\n\nMuchas gracias,\nJose Vicente Carratalá",
     "time": "Ayer"},
]


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def preguntar_ollama(prompt):
    response = requests.post(OLLAMA_URL, json={
        "model": MODELO,
        "prompt": prompt,
        "stream": False
    }, timeout=60)
    response.raise_for_status()
    return response.json()["response"].strip()


@app.route("/")
@login_required
def index():
    return render_template("index.html", username=session.get("username"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))
        return render_template("login.html", error="Email o contraseña incorrectos")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        hashed = generate_password_hash(password)
        try:
            conn = get_db()
            conn.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                         (username, email, hashed))
            conn.commit()
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            for e in EMAILS_DEMO:
                conn.execute("""INSERT INTO emails (user_id, sender_name, sender_email, subject, body, time)
                                VALUES (?, ?, ?, ?, ?, ?)""",
                             (user["id"], e["sender_name"], e["sender_email"],
                              e["subject"], e["body"], e["time"]))
            conn.commit()
            conn.close()
            return redirect(url_for("login"))
        except Exception:
            return render_template("register.html", error="El email o usuario ya existe")
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/emails")
@login_required
def get_emails():
    conn = get_db()
    emails = conn.execute("SELECT * FROM emails WHERE user_id = ? ORDER BY id DESC",
                          (session["user_id"],)).fetchall()
    sent = conn.execute("SELECT * FROM sent_emails WHERE user_id = ? ORDER BY id DESC",
                        (session["user_id"],)).fetchall()
    conn.close()
    return jsonify({
        "emails": [dict(e) for e in emails],
        "sent": [dict(s) for s in sent]
    })


@app.route("/api/emails/<int:email_id>/analyze", methods=["POST"])
@login_required
def analyze_email(email_id):
    conn = get_db()
    email = conn.execute("SELECT * FROM emails WHERE id = ? AND user_id = ?",
                         (email_id, session["user_id"])).fetchone()
    if not email:
        conn.close()
        return jsonify({"error": "Correo no encontrado"}), 404

    try:
        prompt = f"""You are an email classifier. Analyze this email and respond ONLY with a valid JSON object, no explanation, no markdown:

{{"categoria": "soporte", "prioridad": "urgente", "resumen": "frase corta", "respuesta": "respuesta profesional en español"}}

Rules:
- categoria must be exactly one of: soporte, ventas, rrhh, facturacion, general
- prioridad must be exactly one of: urgente, normal, baja
- resumen must be a short sentence in Spanish
- respuesta must be a professional reply in Spanish

Email to analyze:
From: {email['sender_name']} <{email['sender_email']}>
Subject: {email['subject']}
Body: {email['body']}

JSON only:"""

        texto = preguntar_ollama(prompt)
        texto = texto.replace("```json", "").replace("```", "").strip()

        inicio = texto.find("{")
        fin = texto.rfind("}") + 1
        if inicio == -1 or fin == 0:
            raise ValueError("No se encontró JSON en la respuesta")
        texto = texto[inicio:fin]

        parsed = json.loads(texto)

        categorias_validas = ["soporte", "ventas", "rrhh", "facturacion", "general"]
        categoria = parsed.get("categoria", "general")
        categoria = next((c for c in categorias_validas if c in categoria), "general")

        prioridades_validas = ["urgente", "normal", "baja"]
        prioridad = parsed.get("prioridad", "normal")
        prioridad = next((p for p in prioridades_validas if p in prioridad), "normal")

        conn.execute("""UPDATE emails SET category=?, priority=?, summary=?, ai_response=?, unread=0
                        WHERE id=?""",
                     (categoria, prioridad, parsed.get("resumen", ""),
                      parsed.get("respuesta", ""), email_id))
        conn.commit()

        email_updated = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        conn.close()
        return jsonify({"success": True, "email": dict(email_updated)})

    except requests.exceptions.ConnectionError:
        conn.close()
        return jsonify({"error": "Ollama no está ejecutándose."}), 500
    except json.JSONDecodeError:
        conn.close()
        return jsonify({"error": "La IA no devolvió un JSON válido. Inténtalo de nuevo."}), 500
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/emails/<int:email_id>/send", methods=["POST"])
@login_required
def send_response(email_id):
    conn = get_db()
    email = conn.execute("SELECT * FROM emails WHERE id = ? AND user_id = ?",
                         (email_id, session["user_id"])).fetchone()
    if not email:
        conn.close()
        return jsonify({"error": "No encontrado"}), 404

    body = request.json.get("response", "")
    conn.execute("INSERT INTO sent_emails (user_id, to_email, subject, body, time) VALUES (?, ?, ?, ?, ?)",
                 (session["user_id"], email["sender_email"],
                  f"Re: {email['subject']}", body,
                  datetime.now().strftime("%H:%M")))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/compose", methods=["POST"])
@login_required
def compose():
    d = request.json
    conn = get_db()
    conn.execute("INSERT INTO sent_emails (user_id, to_email, subject, body, time) VALUES (?, ?, ?, ?, ?)",
                 (session["user_id"], d.get("to", ""), d.get("subject", ""),
                  d.get("body", ""), datetime.now().strftime("%H:%M")))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


if __name__ == "__main__":
    init_db()
    print("=" * 50)
    print("  MailAI - Abre: http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, port=5000)
