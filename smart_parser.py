import os
import json
import logging
from typing import Optional, Dict, Any
import google.generativeai as genai
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Configuração do modelo
API_KEY = os.getenv("GOOGLE_API_KEY")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower() # 'gemini' ou 'ollama'

if API_KEY and LLM_PROVIDER == "gemini":
    genai.configure(api_key=API_KEY)
elif LLM_PROVIDER == "ollama":
    logger.info(f"SmartParser: Usando Ollama em {OLLAMA_URL}")
else:
    logger.warning("Nenhum provedor de LLM configurado corretamente (GOOGLE_API_KEY ou OLLAMA_BASE_URL).")

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
      "conteudo": { "texto": "...", "incisos": [] }
    }
  ]
}

IMPORTANTE:
- Retorne APENAS o JSON, sem markdown ou explicações.
- Se não conseguir identificar algo, deixe o campo vazio ou nulo.
- Preserve a fidelidade técnica do texto.
"""

class SmartParser:
    def __init__(self, model_name: str = None):
        self.provider = LLM_PROVIDER
        self.model_name = model_name or os.getenv("LLM_MODEL", "gemini-2.0-flash" if self.provider == "gemini" else "llama3")
        
        self.enabled = False
        if self.provider == "gemini" and API_KEY:
            self.model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=PROMPT_SISTEMA
            )
            self.enabled = True
        elif self.provider == "ollama":
            self.enabled = True # Assume valid if configured

    def recuperar_artigo(self, texto_bruto: str, numero_sugerido: str = "") -> Optional[dict]:
        """
        Usa LLM (Gemini ou Ollama) para recuperar a estrutura de um artigo que falhou no regex.
        """
        if not self.enabled:
            return None

        try:
            logger.info(f"SmartParser ({self.provider}): Tentando recuperar Art. {numero_sugerido}")
            prompt = f"{PROMPT_SISTEMA if self.provider == 'ollama' else ''}\n\nConverta este texto de artigo de lei para JSON:\n\n{texto_bruto}"
            
            if self.provider == "gemini":
                response = self.model.generate_content(prompt)
                raw_json = response.text.strip()
            else:
                raw_json = self._call_ollama(prompt)
                
            # Limpa possíveis blocos de código markdown
            if "```json" in raw_json:
                raw_json = raw_json.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_json:
                raw_json = raw_json.split("```")[1].split("```")[0].strip()
                
            dados = json.loads(raw_json)
            
            # Validação mínima do schema
            if "numero" in dados and "estrutura" in dados:
                dados["confianca_ia"] = 0.9
                dados["llm_provider"] = self.provider
                return dados
                
            return None
        except Exception as e:
            logger.error(f"Erro no SmartParser: {e}")
            return None

    def _call_ollama(self, prompt: str) -> str:
        """Chamada direta para a API do Ollama."""
        try:
            with httpx.Client(timeout=60.0) as client:
                payload = {
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
                r = client.post(f"{OLLAMA_URL}/api/generate", json=payload)
                r.raise_for_status()
                return r.json().get("response", "")
        except Exception as e:
            logger.error(f"Erro ao chamar Ollama: {e}")
            raise

# Singleton
smart_parser = SmartParser()

