# Copyright (c) 2026, Friday Labs and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LLMProvider(Document):
	"""LLM provider configuration for Friday agents.

	Each row represents one configured provider instance (e.g., "Production
	Minimax", "Dev OpenAI"). `Agent Profile.model_provider` links to the
	appropriate row. API keys are stored as Frappe Password fields and
	decrypted at runtime when the provider is instantiated.
	"""

	pass
