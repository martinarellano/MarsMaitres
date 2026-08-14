"""Adaptador de Mercado Pago para MarsMaitre.

No guarda tarjetas. El Access Token se inyecta en el servidor mediante
MERCADOPAGO_ACCESS_TOKEN. Se habilita solo después de validar credenciales
de prueba y configurar URLs HTTPS de retorno/webhook.
"""
import json, os, urllib.request, urllib.error

API = "https://api.mercadopago.com"

class MercadoPagoError(Exception):
    pass

class MercadoPago:
    def __init__(self, token=None):
        self.token = token or os.environ.get('MERCADOPAGO_ACCESS_TOKEN','')
        if not self.token:
            raise MercadoPagoError('Falta MERCADOPAGO_ACCESS_TOKEN')

    def request(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            'Authorization': 'Bearer ' + self.token,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return json.loads(res.read() or '{}')
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')
            raise MercadoPagoError(f'Mercado Pago respondió HTTP {exc.code}: {detail[:500]}')

    def create_recurring_plan(self, reason, amount, back_url):
        # Preapproval plan: la configuración final se valida con la cuenta MP.
        return self.request('POST', '/preapproval_plan', {
            'reason': reason,
            'auto_recurring': {'frequency': 1, 'frequency_type': 'months', 'transaction_amount': amount, 'currency_id': 'MXN'},
            'back_url': back_url,
            'payment_methods_allowed': {'payment_types': [{'id': 'credit_card'}, {'id': 'debit_card'}]}
        })

    def create_subscription(self, plan_id, payer_email, back_url):
        return self.request('POST', '/preapproval', {
            'preapproval_plan_id': plan_id,
            'payer_email': payer_email,
            'back_url': back_url,
            'status': 'pending'
        })

    def get_subscription(self, subscription_id):
        return self.request('GET', '/preapproval/' + subscription_id)
