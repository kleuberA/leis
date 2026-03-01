import os
import json
import logging
from typing import Optional
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Configuração do modelo
# O usuário deve fornecer GOOGLE_API_KEY no .env
API_KEY = os.getenv("GOOGLE_API_KEY")
if API_KEY:
    genai.configure(api_key=API_KEY)
else:
    logger.warning("GOOGLE_API_KEY não encontrada. SmartParser operará em modo offline (inativo).")

PROMPT_SISTEMA = """
Você é um especialista em direito brasileiro e processamento de dados legislativos.
Sua tarefa é converter o texto bruto de um ARTIGO de lei brasileira em uma estrutura JSON específica.

REGRAS DE ESTRUTURA:
1. Identifique o Caput, Parágrafos, Incisos e Alíneas.
2. O "caput" é o texto principal do artigo logo após seu número.
3. Parágrafos podem ser "Parágrafo único" ou numerados (§ 1º, § 2º, etc.).
4. Incisos são numerados em romanos (I, II, III, etc.).
5. Alíneas são identificadas por letras seguidas de parênteses (a), b), c), etc.).
6. Metadados: Identifique trechos entre parênteses que indicam alterações (ex: "Redação dada pela Lei nº...").

SCHEMA JSON ESPERADO:
{
  "numero": "string (ex: 5º, 15, 4º-A)",
  "estrutura": [
    {
      "tipo": "caput",
      "conteudo": {
        "texto": "texto do caput sem o número Art. X",
        "incisos": [
            {
                "tipo": "inciso",
                "numero": "I",
                "conteudo": {
                    "texto": "texto do inciso",
                    "alineas": [{"tipo": "alinea", "letra": "a", "texto": "..."}]
                }
            }
        ],
        "metadados": [{"tipo": "redacao", "norma": "Lei X", "ano": "2023"}]
      }
    },
    {
      "tipo": "paragrafo",
      "numero": "1" ou "único",
      "conteudo": { ... mesmo formato do caput ... }
    }
  ]
}

IMPORTANTE:
- Retorne APENAS o JSON, sem markdown ou explicações.
- Se não conseguir identificar algo, deixe o campo vazio ou nulo.
- Preserve a fidelidade técnica do texto.
"""

class SmartParser:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.enabled = bool(API_KEY)
        if self.enabled:
            self.model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=PROMPT_SISTEMA
            )

    def recuperar_artigo(self, texto_bruto: str, numero_sugerido: str = "") -> Optional[dict]:
        """
        Usa LLM para tentar recuperar a estrutura de um artigo que falhou no regex.
        """
        if not self.enabled:
            return None

        try:
            logger.info(f"SmartParser: Tentando recuperar Art. {numero_sugerido}")
            prompt = f"Converta este texto de artigo de lei para JSON:\n\n{texto_bruto}"
            
            response = self.model.generate_content(prompt)
            
            # Limpa possíveis blocos de código markdown
            raw_json = response.text.strip()
            if raw_json.startswith("```json"):
                raw_json = raw_json[7:-3].strip()
            elif raw_json.startswith("```"):
                raw_json = raw_json[3:-3].strip()
                
            dados = json.loads(raw_json)
            
            # Validação mínima do schema
            if "numero" in dados and "estrutura" in dados:
                dados["confianca_ia"] = 0.9  # IA gera com alta confiança estrutural se o JSON for válido
                return dados
                
            return None
        except Exception as e:
            logger.error(f"Erro no SmartParser: {e}")
            return None

# Singleton
smart_parser = SmartParser()
