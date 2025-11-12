"""
Serveur Flask pour gérer les webhooks Stripe
Optimisé pour Railway
VERSION CORRIGÉE - Email de confirmation sans identifiants
"""

from flask import Flask, request, jsonify
import stripe
import sqlite3
import secrets
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# Configuration depuis variables d'environnement
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

# Configuration Email (optionnel)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "maryem.gueri@gmail.com"
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')

if not STRIPE_SECRET_KEY:
    raise ValueError("❌ STRIPE_SECRET_KEY manquant dans les variables d'environnement")

stripe.api_key = STRIPE_SECRET_KEY

# Database path - Railway compatible
DATABASE = os.path.join(os.path.dirname(__file__), 'licenses.db')


def init_database():
    """Initialise la base de données SQLite"""
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS licenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                expiry_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                last_renewal TEXT,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ Base de données initialisée avec succès")
    except Exception as e:
        print(f"❌ Erreur initialisation base de données : {e}")


def send_confirmation_email(email, expiry_date, is_renewal=False):
    """Envoie l'email de confirmation d'abonnement"""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("⚠️ Configuration email manquante - Email non envoyé")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = SMTP_USER
        msg['To'] = email

        if is_renewal:
            msg['Subject'] = "🔄 Renouvellement de votre abonnement Robot CFE"
            titre = "Votre abonnement a été renouvelé !"
            message_principal = "Votre abonnement Robot CFE a été renouvelé avec succès."
        else:
            msg['Subject'] = "🎉 Bienvenue sur Robot CFE - Abonnement activé"
            titre = "Bienvenue sur Robot CFE !"
            message_principal = "Votre abonnement a été activé avec succès."

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #8F3FFF;">{titre}</h2>

                <p>{message_principal}</p>

                <div style="background: #f5f5f5; padding: 20px; border-radius: 10px; margin: 20px 0;">
                    <h3>📅 Informations de votre abonnement :</h3>
                    <p><strong>Statut :</strong> <span style="color: #28a745;">✓ Actif</span></p>
                    <p><strong>Valable jusqu'au :</strong> {expiry_date}</p>
                    <p><strong>Renouvellement :</strong> Automatique</p>
                </div>

                <div style="background: #e8f4fd; padding: 15px; border-left: 4px solid #2196F3; margin: 20px 0;">
                    <p><strong>ℹ️ Connexion à RobotCFE :</strong></p>
                    <ul>
                        <li>Utilisez vos identifiants de compte existants</li>
                        <li>Lancez RobotCFE.exe et connectez-vous normalement</li>
                        <li>Votre abonnement est maintenant actif</li>
                    </ul>
                </div>

                <div style="background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0;">
                    <p><strong>⚠️ Important :</strong></p>
                    <ul>
                        <li>Votre abonnement se renouvelle automatiquement chaque année</li>
                        <li>Vous recevrez un email de confirmation avant chaque renouvellement</li>
                        <li>Vous pouvez annuler à tout moment depuis votre espace client</li>
                    </ul>
                </div>

                <p>Besoin d'aide ? Contactez-nous à <a href="mailto:{SMTP_USER}">{SMTP_USER}</a></p>

                <hr style="margin: 30px 0; border: none; border-top: 1px solid #ddd;">
                <p style="color: #888; font-size: 12px;">
                    © 2025 Robot CFE. Tous droits réservés.
                </p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html, 'html'))

        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()

        print(f"✅ Email envoyé à {email}")
        return True

    except Exception as e:
        print(f"❌ Erreur envoi email : {e}")
        return False


def create_license(email, customer_id, subscription_id):
    """Crée une nouvelle licence après paiement Stripe"""
    created_at = datetime.now().isoformat()
    expiry_date = (datetime.now() + timedelta(days=365)).isoformat()

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO licenses 
            (email, expiry_date, status, created_at, 
             stripe_customer_id, stripe_subscription_id)
            VALUES (?, ?, 'active', ?, ?, ?)
        ''', (email, expiry_date, created_at, customer_id, subscription_id))

        conn.commit()
        print(f"✅ Licence créée pour {email}")

        # Envoyer l'email de confirmation
        send_confirmation_email(email, expiry_date[:10], is_renewal=False)

        return expiry_date

    except sqlite3.IntegrityError as e:
        print(f"⚠️ Email {email} existe déjà : {e}")
        return None
    finally:
        conn.close()


def renew_license(email):
    """Renouvelle une licence existante"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("SELECT expiry_date FROM licenses WHERE email = ?", (email,))
    result = cursor.fetchone()

    if not result:
        conn.close()
        print(f"❌ Aucune licence pour {email}")
        return False

    current_expiry = result[0]
    current_expiry_dt = datetime.fromisoformat(current_expiry)

    # Ajouter 1 an
    if current_expiry_dt < datetime.now():
        new_expiry = datetime.now() + timedelta(days=365)
    else:
        new_expiry = current_expiry_dt + timedelta(days=365)

    new_expiry_iso = new_expiry.isoformat()
    last_renewal = datetime.now().isoformat()

    cursor.execute('''
        UPDATE licenses 
        SET expiry_date = ?, status = 'active', last_renewal = ?
        WHERE email = ?
    ''', (new_expiry_iso, last_renewal, email))

    conn.commit()
    conn.close()

    print(f"✅ Licence renouvelée pour {email} jusqu'au {new_expiry_iso[:10]}")

    # Envoyer l'email de renouvellement
    send_confirmation_email(email, new_expiry_iso[:10], is_renewal=True)

    return True


def suspend_license(email):
    """Suspend une licence (impayé)"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("UPDATE licenses SET status = 'suspended' WHERE email = ?", (email,))

    conn.commit()
    conn.close()

    print(f"⚠️ Licence suspendue pour {email}")


# ==========================================
# ROUTES API
# ==========================================

@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """Reçoit les webhooks Stripe"""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    # Vérifier si webhook secret configuré
    if not STRIPE_WEBHOOK_SECRET:
        print("⚠️ STRIPE_WEBHOOK_SECRET non configuré - Validation désactivée")
        try:
            event = stripe.Event.construct_from(request.json, stripe.api_key)
        except Exception as e:
            print(f"❌ Erreur parsing event : {e}")
            return jsonify({'error': 'Invalid payload'}), 400
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            print("❌ Payload invalide")
            return jsonify({'error': 'Invalid payload'}), 400
        except stripe.error.SignatureVerificationError:
            print("❌ Signature invalide")
            return jsonify({'error': 'Invalid signature'}), 400

    print(f"📩 Webhook reçu : {event['type']}")

    # Nouveau paiement (abonnement créé)
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_email = session.get('customer_email')
        customer_id = session.get('customer')
        subscription_id = session.get('subscription')

        print(f"💳 Nouveau paiement pour {customer_email}")

        # Créer la licence
        create_license(customer_email, customer_id, subscription_id)

        return jsonify({'status': 'success', 'action': 'created'}), 200

    # Renouvellement automatique (facture payée)
    elif event['type'] == 'invoice.paid':
        invoice = event['data']['object']

        # Ignorer la première facture (déjà traitée par checkout.session.completed)
        if invoice.get('billing_reason') == 'subscription_create':
            return jsonify({'status': 'ignored'}), 200

        customer_id = invoice.get('customer')

        # Récupérer l'email du client
        try:
            customer = stripe.Customer.retrieve(customer_id)
            customer_email = customer.get('email')

            print(f"🔄 Renouvellement pour {customer_email}")

            # Renouveler la licence
            renew_license(customer_email)

            return jsonify({'status': 'success', 'action': 'renewed'}), 200
        except Exception as e:
            print(f"❌ Erreur renouvellement : {e}")
            return jsonify({'error': str(e)}), 500

    # Paiement échoué
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        customer_id = invoice.get('customer')

        try:
            customer = stripe.Customer.retrieve(customer_id)
            customer_email = customer.get('email')

            print(f"❌ Paiement échoué pour {customer_email}")

            # Suspendre la licence
            suspend_license(customer_email)

            return jsonify({'status': 'success', 'action': 'suspended'}), 200
        except Exception as e:
            print(f"❌ Erreur suspension : {e}")
            return jsonify({'error': str(e)}), 500

    # Abonnement annulé
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        customer_id = subscription.get('customer')

        try:
            customer = stripe.Customer.retrieve(customer_id)
            customer_email = customer.get('email')

            print(f"🚫 Abonnement annulé pour {customer_email}")

            suspend_license(customer_email)

            return jsonify({'status': 'success', 'action': 'cancelled'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    else:
        print(f"ℹ️ Événement ignoré : {event['type']}")
        return jsonify({'status': 'ignored'}), 200


@app.route('/api/check_subscription', methods=['POST'])
def check_subscription():
    """Vérifie si un utilisateur a un abonnement actif"""
    data = request.json
    email = data.get('email')

    if not email:
        return jsonify({'error': 'Email required'}), 400

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT expiry_date, status 
        FROM licenses 
        WHERE email = ?
    ''', (email,))

    result = cursor.fetchone()
    conn.close()

    if not result:
        return jsonify({
            'active': False,
            'status': 'no_subscription',
            'message': 'Aucun abonnement trouvé'
        }), 200

    expiry_date, status = result
    expiry_dt = datetime.fromisoformat(expiry_date)
    days_remaining = (expiry_dt - datetime.now()).days

    if status == 'suspended':
        return jsonify({
            'active': False,
            'status': 'suspended',
            'message': 'Abonnement suspendu'
        }), 200

    if days_remaining < 0:
        return jsonify({
            'active': False,
            'status': 'expired',
            'message': 'Abonnement expiré'
        }), 200

    return jsonify({
        'active': True,
        'status': 'active',
        'expiry_date': expiry_date[:10],
        'days_remaining': days_remaining
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        'status': 'ok',
        'database': 'connected' if os.path.exists(DATABASE) else 'not_found'
    }), 200


@app.route('/', methods=['GET'])
def home():
    """Page d'accueil"""
    return jsonify({
        'service': 'Robot CFE API',
        'status': 'running',
        'version': '1.0',
        'endpoints': {
            'webhook': '/webhook/stripe',
            'check': '/api/check_subscription',
            'health': '/health'
        }
    }), 200


# ⚠️ CRITIQUE : Initialiser la DB au chargement du module (pour Gunicorn)
init_database()


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 DÉMARRAGE SERVEUR API ROBOT CFE")
    print("=" * 60)

    # Port pour Railway (ou 5000 en local)
    port = int(os.environ.get('PORT', 5000))

    print(f"\n📡 Serveur démarré sur http://0.0.0.0:{port}")
    print("📩 Webhook Stripe : /webhook/stripe")
    print("🔍 Check abonnement : /api/check_subscription")
    print("\n" + "=" * 60 + "\n")

    # Railway nécessite host='0.0.0.0'
    app.run(host='0.0.0.0', port=port, debug=False)