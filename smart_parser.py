import os
import re
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
Você é um especialista em direito brasileiro e processamento de dados legislativos de ALTA PRECISÃO.
Sua tarefa é converter o texto bruto de um ARTIGO de lei brasileira em uma estrutura JSON específica.

REGRAS CRÍTICAS:
1. FIDELIDADE ABSOLUTA: Não altere uma única letra do texto legal. Não resuma, não parafraseie.
2. ESTRUTURA:
   - "caput": Texto principal do artigo.
   - "paragrafo": § 1º, § 2º ou "único".
   - "inciso": I, II, III (romanos).
   - "alinea": a), b), c) (letras).
3. HIERARQUIA: Garanta que incisos dentro de parágrafos estejam corretamente aninhados.
4. METADADOS: Capture notas de redação (ex: "Redação dada pela Lei...") no campo metadados.
5. NÃO ALUCINE: Se o texto estiver truncado ou ilegível, preserve o que existe. Nunca invente conteúdo.

SCHEMA JSON:
{
  "numero": "string",
  "estrutura": [
    {
      "tipo": "caput" | "paragrafo",
      "numero": "string" (apenas para paragrafo),
      "conteudo": {
        "texto": "string",
        "incisos": [
          {
            "numero": "string",
            "conteudo": { "texto": "string", "alineas": [...] }
          }
        ],
        "metadados": [{"tipo": "string", "norma": "string", "ano": "string"}]
      }
    }
  ]
}

IMPORTANTE: Retorne APENAS o JSON bruto.
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

    def recuperar_artigo(self, texto_bruto: str, numero_sugerido: str = "", contexto: str = "") -> Optional[dict]:
        """
        Usa LLM para recuperar a estrutura de um artigo que falhou no regex.
        Inclui contexto hierárquico (Título/Capítulo) para maior precisão.
        """
        if not self.enabled:
            return None

        try:
            logger.info(f"SmartParser ({self.provider}): Tentando recuperar Art. {numero_sugerido}")
            
            prompt_contexto = f"\nCONTEXTO DA LEI: {contexto}\n" if contexto else ""
            prompt = f"{PROMPT_SISTEMA if self.provider == 'ollama' else ''}\n{prompt_contexto}\nConverta este texto de artigo para JSON:\n\n{texto_bruto}"
            
            if self.provider == "gemini":
                response = self.model.generate_content(prompt)
                raw_json = response.text.strip()
            else:
                raw_json = self._call_ollama(prompt)
                
            # Limpeza robusta de blocos de código
            raw_json = re.sub(r"```json\s*", "", raw_json)
            raw_json = re.sub(r"```\s*$", "", raw_json)
            raw_json = raw_json.strip()
                
            dados = json.loads(raw_json)
            
            # Validação rigorosa dos campos obrigatórios
            if "numero" in dados and "estrutura" in dados:
                # Normalização básica de campos para evitar erros no frontend
                for item in dados["estrutura"]:
                    if "conteudo" not in item: item["conteudo"] = {"texto": ""}
                    if "incisos" not in item["conteudo"]: item["conteudo"]["incisos"] = []
                
                dados["confianca_ia"] = 0.95
                dados["llm_provider"] = self.provider
                dados["original_prompt_contexto"] = contexto
                return dados
                
            return None
        except Exception as e:
            logger.error(f"Erro no SmartParser ao processar Art. {numero_sugerido}: {e}")
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

