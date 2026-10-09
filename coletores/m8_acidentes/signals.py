"""
Módulo 8 — extração heurística de sinais (SignaisVinculo/SignaisGravidade)
a partir do texto do comunicado.

AVISO — leia antes de confiar nisto em produção: esta é a peça mais
arriscada de todo o Módulo 8. scoring.py (a matemática da regra) está
testado e correto. Este arquivo, que decide QUAIS sinais estão presentes
num texto real, é heurística por palavra-chave e NÃO foi validada contra
nenhum documento real da SEMAD — só contra os resumos de uma linha que a
própria Carta Operacional dá para os 21 casos congelados (ver
test_signals.py). Um documento real tem muito mais nuance do que um
resumo de uma linha, e palavras-chave sozinhas erram por dois lados:

  - falso positivo: "concentrado" aparece num pigmento de tinta, não em
    minério (carta M8-A06 já veio como caso justamente por causa disso).
  - falso negativo: o texto descreve o mesmo fato sem usar nenhuma das
    palavras-chave cadastradas.

Por isso: todo caso com faixa_vinculo in ('provavel',) precisa ir para
revisão humana de qualquer forma (é a própria regra da carta, §8 faixa
5-7), o que dá uma rede de segurança para o extrator errar para cima. O
risco maior é um falso negativo que joga um caso minerário real para
'contextual'/'descartado' sem alerta. Por isso: NÃO rodar isto contra
dados reais em modo "grava direto e publica" sem a Rapha revisar uma
amostra real primeiro — ver `revisao_humana` obrigatória em main.py, que
mantém TODO evento (mesmo os 'confirmado') com revisao_humana='Pendente'
até ela aprovar.
"""
import re
from dataclasses import dataclass
from typing import Optional

from scoring import SignaisVinculo, SignaisGravidade

# ----------------------------------------------------------------------------
# Vocabulário — carta §8 (vínculo) e §9/§10 (gravidade/gatilhos)
# ----------------------------------------------------------------------------

_KW_MODALIDADE_MINERACAO = [
    "mineração", "minerário", "minerária", "lavra", "atividade minerária",
]
_KW_MATERIAL_MINERAL = [
    "minério", "minerio", "rejeito", "polpa mineral", "polpa de minério",
    "estéril", "esteril", "sedimento", "turbidez",
]
_KW_INSUMO_ESTRUTURA = [
    "nitrato de amônia", "nitrato de amonia", "polímero", "polimero",
    "sump", "cava", "pilha de estéril", "usina", "barragem", "sirene",
]
_KW_ACIDENTE_RODOVIARIO = [
    "tombamento", "acidente rodoviário", "acidente rodoviario",
    "transporte rodoviário", "transporte rodoviario",
]
# Produtos claramente não-minerários vistos na amostra negativa — carta
# §12: pigmento, produto industrial, carvão vegetal, óleos lubrificantes,
# emulsão asfáltica, cimento asfáltico, leite cru, tintas.
_KW_PRODUTO_NAO_MINERARIO = [
    "pigmento", "concentrado alcatone", "lifewood", "carvão vegetal",
    "carvao vegetal", "óleo lubrificante", "oleo lubrificante",
    "emulsão asfáltica", "emulsao asfaltica", "cimento asfáltico",
    "cimento asfaltico", "leite cru", "tinta", "usina de asfalto",
]

_KW_MUNICIPIOS_MINERADORES = [
    # lista não-exaustiva de municípios mineradores citados na própria
    # carta — usar só como sinal de DESEMPATE (§8), nunca sozinho.
    "conceição do pará", "conceicao do para", "conceição do mato dentro",
    "conceicao do mato dentro", "nova lima", "congonhas", "sabará",
    "sabara", "mariana", "barão de cocais", "barao de cocais", "itabira",
    "itatiaiuçu", "itatiaiucu",
]

_KW_CURSO_DAGUA = ["córrego", "corrego", "ribeirão", "ribeirao", "rio ", "curso d'água", "curso dagua", "captação", "captacao", "abastecimento"]
_KW_RISCO_ESTRUTURAL = ["barragem", "sirene", "rompimento", "risco de rompimento", "interrupção de abastecimento", "interrupcao de abastecimento"]
_KW_VITIMAS_EVACUACAO = ["vítima", "vitima", "evacuação", "evacuacao", "bloqueio", "risco à comunidade", "risco a comunidade"]


_NEGACOES = ["sem ", "não ", "nao ", "ausência de ", "ausencia de ", "nenhum ", "nenhuma "]
_JANELA_NEGACAO_CHARS = 25  # olha essa quantidade de caracteres antes da palavra-chave


def _tem_negacao_antes(texto_lower: str, posicao: int) -> bool:
    """Guarda simples contra negação: 'sem vínculo minerário comprovado' não
    deve contar como sinal positivo de 'minerário'. Não é análise
    sintática de verdade — é a razão pela qual este arquivo continua
    marcado como não-validado contra documento real (ver aviso no topo)."""
    inicio = max(0, posicao - _JANELA_NEGACAO_CHARS)
    janela = texto_lower[inicio:posicao]
    return any(neg in janela for neg in _NEGACOES)


def _contem_alguma(texto: str, palavras: list) -> bool:
    t = texto.lower()
    for p in palavras:
        pos = t.find(p)
        while pos != -1:
            if not _tem_negacao_antes(t, pos):
                return True
            pos = t.find(p, pos + 1)
    return False


def extrair_signais_vinculo(texto: str, local_descrito: str = "", empresa_citada: str = "") -> SignaisVinculo:
    base = f"{texto}\n{local_descrito}\n{empresa_citada}"

    tem_produto_nao_minerario = _contem_alguma(base, _KW_PRODUTO_NAO_MINERARIO)
    tem_material = _contem_alguma(base, _KW_MATERIAL_MINERAL) and not tem_produto_nao_minerario
    tem_modalidade = _contem_alguma(base, _KW_MODALIDADE_MINERACAO)
    tem_insumo = _contem_alguma(base, _KW_INSUMO_ESTRUTURA)
    tem_rodoviario = _contem_alguma(base, _KW_ACIDENTE_RODOVIARIO)
    tem_municipio_minerador = _contem_alguma(base, _KW_MUNICIPIOS_MINERADORES)

    return SignaisVinculo(
        modalidade_mineracao=tem_modalidade,
        mina_identificada=False,  # TODO: exige cruzamento com cadastro de minas/empresas (carta §8) — não dá para inferir só por regex
        material_mineral=tem_material,
        insumo_estrutura_vinculada=tem_insumo,
        municipio_minerador=tem_municipio_minerador,
        produto_causa_nao_mineraria=tem_produto_nao_minerario and not (tem_material or tem_modalidade or tem_insumo),
        acidente_rodoviario_comum=tem_rodoviario and not (tem_material or tem_modalidade or tem_insumo),
    )


def extrair_signais_gravidade(texto: str, atraso_comunicacao_minutos: Optional[int] = None) -> SignaisGravidade:
    return SignaisGravidade(
        atingiu_ou_pode_atingir_curso_dagua=_contem_alguma(texto, _KW_CURSO_DAGUA),
        ultrapassou_limites_operacao=("fora da contenção" in texto.lower() or "área externa" in texto.lower() or "area externa" in texto.lower()),
        rejeito_ou_produto_perigoso_ou_volume_significativo=_contem_alguma(texto, ["rejeito", "produto perigoso", "volume significativo"]),
        risco_estrutural_ou_interrupcao_abastecimento=_contem_alguma(texto, _KW_RISCO_ESTRUTURAL),
        comunicacao_mais_de_6_horas=(atraso_comunicacao_minutos is not None and atraso_comunicacao_minutos > 6 * 60),
        vitimas_evacuacao_bloqueio_ou_risco_comunidade=_contem_alguma(texto, _KW_VITIMAS_EVACUACAO),
    )


# ----------------------------------------------------------------------------
# Evidências por campo (Checklist Completo de Enriquecimento Pré-Release,
# seção "Evidências e proveniência": "Exigir ao menos uma evidência ativa
# para cada frase factual" e "guardar... trecho literal"). Os sinais acima
# só dizem SE algo foi encontrado (True/False); as funções abaixo dizem
# ONDE — o trecho exato do texto que sustenta cada sinal, pra gravar em
# `evidencias` (campo `trecho_literal`). Reusa a mesma lógica de match e
# guarda de negação de `_contem_alguma`, só que devolvendo o trecho em vez
# de um booleano.
# ----------------------------------------------------------------------------
_JANELA_TRECHO_CHARS = 60  # contexto ao redor da palavra-chave, pra cada lado


def _trechos_para(texto: str, palavras: list, campo: str) -> list:
    """Retorna uma lista de {campo, trecho_literal, palavra_gatilho} — uma
    entrada por ocorrência não-negada de qualquer palavra de `palavras`
    em `texto`. Dedupa por (campo, trecho) pra não gravar a mesma frase
    duas vezes quando duas palavras da mesma lista caem na mesma janela."""
    t = texto.lower()
    encontrados = []
    vistos = set()
    for p in palavras:
        pos = t.find(p)
        while pos != -1:
            if not _tem_negacao_antes(t, pos):
                inicio = max(0, pos - _JANELA_TRECHO_CHARS)
                fim = min(len(texto), pos + len(p) + _JANELA_TRECHO_CHARS)
                trecho = texto[inicio:fim].strip()
                chave = (campo, trecho)
                if chave not in vistos and trecho:
                    vistos.add(chave)
                    encontrados.append({"campo": campo, "trecho_literal": trecho, "palavra_gatilho": p})
            pos = t.find(p, pos + 1)
    return encontrados


def extrair_evidencias_vinculo(texto: str, local_descrito: str = "", empresa_citada: str = "") -> list:
    """Evidências por trás de SignaisVinculo — uma entrada por campo que
    disparou algum sinal positivo do score de vínculo (carta §8)."""
    base = f"{texto}\n{local_descrito}\n{empresa_citada}"
    evidencias = []
    evidencias += _trechos_para(base, _KW_MODALIDADE_MINERACAO, "modalidade_mineracao")
    evidencias += _trechos_para(base, _KW_MATERIAL_MINERAL, "material_mineral")
    evidencias += _trechos_para(base, _KW_INSUMO_ESTRUTURA, "insumo_estrutura_vinculada")
    evidencias += _trechos_para(base, _KW_MUNICIPIOS_MINERADORES, "municipio_minerador")
    evidencias += _trechos_para(base, _KW_PRODUTO_NAO_MINERARIO, "produto_causa_nao_mineraria")
    evidencias += _trechos_para(base, _KW_ACIDENTE_RODOVIARIO, "acidente_rodoviario_comum")
    return evidencias


def extrair_evidencias_gravidade(texto: str) -> list:
    """Evidências por trás de SignaisGravidade (carta §9/§10)."""
    evidencias = []
    evidencias += _trechos_para(texto, _KW_CURSO_DAGUA, "atingiu_ou_pode_atingir_curso_dagua")
    evidencias += _trechos_para(texto, ["rejeito", "produto perigoso", "volume significativo"],
                                 "rejeito_ou_produto_perigoso_ou_volume_significativo")
    evidencias += _trechos_para(texto, _KW_RISCO_ESTRUTURAL, "risco_estrutural_ou_interrupcao_abastecimento")
    evidencias += _trechos_para(texto, _KW_VITIMAS_EVACUACAO, "vitimas_evacuacao_bloqueio_ou_risco_comunidade")
    return evidencias
