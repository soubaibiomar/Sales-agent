"""
Notification Templates and Default Seed Catalog.
Step 07: Durable Workflows, Notifications and Peripheral Integrations
(Controls 28, 31, 42-44, 57-59, 63-64; SAI-11; ADR-007)
"""
from typing import Dict, Any, List

DEFAULT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "template_code": "ORDER_CONFIRMED",
        "channel_type": "EMAIL",
        "message_class": "TRANSACTIONAL",
        "language": "fr-FR",
        "subject_template": "Confirmation de votre commande {{order_id}}",
        "body_template": "Bonjour {{customer_name}},\n\nNous confirmons votre commande {{order_id}} pour un montant de {{amount_formatted}} MAD. Nous préparons vos articles.\n\nMerci de votre confiance,\nL'équipe commerciale.",
        "variables": ["order_id", "customer_name", "amount_formatted"]
    },
    {
        "template_code": "ORDER_CONFIRMED",
        "channel_type": "WHATSAPP",
        "message_class": "TRANSACTIONAL",
        "language": "fr-FR",
        "subject_template": None,
        "body_template": "Bonjour {{customer_name}}! Votre commande {{order_id}} ({{amount_formatted}} MAD) est confirmée et en cours de préparation. Suivez votre colis ici: {{tracking_url}}",
        "variables": ["order_id", "customer_name", "amount_formatted", "tracking_url"]
    },
    {
        "template_code": "ORDER_CONFIRMED",
        "channel_type": "WHATSAPP",
        "message_class": "TRANSACTIONAL",
        "language": "ary-Latn",
        "subject_template": None,
        "body_template": "Salam {{customer_name}}! Commande dyalk {{order_id}} dial {{amount_formatted}} MAD rahaa m-confirmiya. Ghadi twselk f a9rab wa9t insha'Allah.",
        "variables": ["order_id", "customer_name", "amount_formatted"]
    },
    {
        "template_code": "QUOTE_APPROVAL_REQUIRED",
        "channel_type": "EMAIL",
        "message_class": "TRANSACTIONAL",
        "language": "fr-FR",
        "subject_template": "[URGENT] Approbation requise pour le devis {{quote_id}}",
        "body_template": "Bonjour Manager,\n\nLe devis {{quote_id}} pour le compte {{account_name}} nécessite votre validation en raison d'une remise de {{discount_percent}}% (Montant: {{total_amount}} MAD).\n\nVeuillez valider sur la console: {{approval_url}}",
        "variables": ["quote_id", "account_name", "discount_percent", "total_amount", "approval_url"]
    },
    {
        "template_code": "APPOINTMENT_REMINDER",
        "channel_type": "WHATSAPP",
        "message_class": "SERVICE",
        "language": "fr-FR",
        "subject_template": None,
        "body_template": "Rappel: Votre rendez-vous commercial avec {{staff_name}} est prévu le {{appointment_date}} à {{appointment_time}}.",
        "variables": ["staff_name", "appointment_date", "appointment_time"]
    },
    {
        "template_code": "MARKETING_PROMOTION",
        "channel_type": "WHATSAPP",
        "message_class": "MARKETING",
        "language": "fr-FR",
        "subject_template": None,
        "body_template": "Offre exclusive: Profitez de 15% sur nos nouveaux produits IT avec le code PROMO15 jusqu'à vendredi! Répondez STOP pour vous désabonner.",
        "variables": []
    }
]


def render_template_string(template_str: str, variables: Dict[str, Any]) -> str:
    """Substitutes {{variable_name}} and {variable_name} tokens with provided values."""
    if not template_str:
        return ""
    rendered = template_str
    for k, v in variables.items():
        rendered = rendered.replace(f"{{{{{k}}}}}", str(v))
        rendered = rendered.replace(f"{{{k}}}", str(v))
    return rendered
