"""
Régua de criticidade CRIT-V1.2 (M8 e M9A) — determinística, sem IA, auditável.

Esta régua responde "isto vira uma pauta relevante?" e NÃO substitui o score anterior
(SCORE-M9A-V0.2 / SCORE-M8-V1.0), que continua existindo como histórico. A criticidade é gravada como
uma NOVA versão de score (versao_score='CRIT-V1.2'), sem apagar nenhuma linha antiga.

Níveis (do menor para o maior): ROTINA, BAIXA, MEDIA, ALTA, CRITICO.
Prioridade operacional derivada: CRITICO=A, ALTA=B, MEDIA=C, BAIXA/ROTINA=D.
Só MEDIA, ALTA e CRITICO disputam a seleção (piso). Tudo que é número (limites de idade, área, listas de
empresas e minerais, palavras-chave) vem de um dicionário de PARÂMETROS versionado
(comum/criticidade_parametros_v1_2.json, espelhado na tabela criticidade_parametros do banco); mudar um valor
= criar nova versão de parâmetros, nunca editar a anterior.

Estado fora da escala: NAO_AVALIAVEL. Caso sem texto oficial lido (falha de extração, documento não aberto por
limite de requisições, sem evidência suficiente) NÃO recebe julgamento editorial: não é ROTINA, não tem prioridade,
fica fora da fila e da IA até a evidência existir. ROTINA é só para ato/comunicado lido e julgado rotineiro.

Estados intermediários (V1.2): POTENCIAL_CRITICO_PENDENTE_EVIDENCIA e POTENCIAL_ALTA_PENDENTE_EVIDENCIA. Se a régua
reconhece um possível CRITICO ou ALTA mas falta evidência estruturada, o caso NÃO desce em silêncio para MEDIA: fica
fora da escala, sem prioridade definitiva, fora da fila e da IA, e é recalculado quando a evidência chegar.
Classificação PROVISÓRIA (caso curado sem tipo oficial; M8 com agravante só por palavra-chave) nunca é selecionável.

Duas premissas corrigidas em relação à fórmula antiga (decisão da Raphaela, 14/10/2026):
  P1. Pedido/protocolo NUNCA vale como ato efetivado: fase "pedido" limita o caso a BAIXA, mesmo que o tipo
      cite cessão, renúncia, guia etc.
  P2. ROTINA anula os demais gatilhos: se o tipo é rotina (TAH, documento diverso, exigência...), nenhuma outra
      palavra-chave, empresa, mineral ou área conta.

Idade (atualidade): um caso só mantém o nível N se a idade do ato for <= limite de N; passando do limite ele
desce para o primeiro nível abaixo cujo limite ainda é respeitado (CRITICO 180d, ALTA 365d, MEDIA 1095d no M9A;
o M8 usa limites próprios, bem menores, também parametrizados). Sem data confiável o teto é BAIXA.
"""
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Sequence

VERSAO_REGRA = "CRIT-V1.2"
_NIVEIS_PADRAO = ["ROTINA", "BAIXA", "MEDIA", "ALTA", "CRITICO"]
_CAMINHO_PARAMETROS_V1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "criticidade_parametros_v1_2.json")
ESTADO_NAO_AVALIAVEL = "NAO_AVALIAVEL"
ESTADO_POTENCIAL_CRITICO = "POTENCIAL_CRITICO_PENDENTE_EVIDENCIA"
ESTADO_POTENCIAL_ALTA = "POTENCIAL_ALTA_PENDENTE_EVIDENCIA"
ESTADOS_FORA_DA_ESCALA = (ESTADO_NAO_AVALIAVEL, ESTADO_POTENCIAL_CRITICO, ESTADO_POTENCIAL_ALTA)
ORIGEM_CURADA = "curada"

_STOPWORDS = {"de", "da", "do", "das", "dos", "e", "em"}  # mesma normalização de classificacao_scm.normalizar_termo


def carregar_parametros(caminho: Optional[str] = None) -> dict:
    with open(caminho or _CAMINHO_PARAMETROS_V1, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------
# Texto / casamento de palavras-chave
# ----------------------------------------------------------------------------

def normalizar(texto: Optional[str]) -> str:
    """Minúsculas, sem acento, sem pontuação, sem preposições curtas, espaço único (mesmo critério de
    classificacao_scm.normalizar_termo)."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(p for p in t.split() if p not in _STOPWORDS)


def _casa(tokens: Sequence[str], palavra: str) -> bool:
    """`palavra` (já em forma normalizável) casa se seus tokens aparecem CONTÍGUOS em `tokens`. Um token que
    termina em '*' casa por prefixo ('aprov*' casa 'aprovada'); sem '*' casa o token inteiro. Isso evita o
    erro de substring (ex.: 'art' dentro de 'particular')."""
    pecas = []  # (token normalizado, casa por prefixo?)
    for p in palavra.split():
        tok = normalizar(p.replace("*", ""))
        if tok:
            pecas.append((tok, p.endswith("*")))
    n = len(pecas)
    if n == 0:
        return False
    for i in range(len(tokens) - n + 1):
        if all((tokens[i + j].startswith(tok) if pref else tokens[i + j] == tok)
               for j, (tok, pref) in enumerate(pecas)):
            return True
    return False


def _contem(tokens: Sequence[str], palavras: Iterable[str]) -> bool:
    return any(_casa(tokens, p) for p in palavras)


# ----------------------------------------------------------------------------
# Níveis, idade
# ----------------------------------------------------------------------------

def _idx(nivel: str, niveis: Sequence[str]) -> int:
    return list(niveis).index(nivel)


def _menor(a: str, b: str, niveis: Sequence[str]) -> str:
    return a if _idx(a, niveis) <= _idx(b, niveis) else b


def _para_data(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "nat", "<na>"):
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _aplicar_idade(nivel: str, idade: Optional[int], limites: Dict[str, int], teto_sem_data: str,
                   niveis: Sequence[str], motivos: List[str]) -> str:
    """Cascata: desce até o primeiro nível cujo limite de idade a idade respeita. Sem limite definido para
    o nível (BAIXA/ROTINA) não há restrição de idade."""
    if _idx(nivel, niveis) <= _idx("BAIXA", niveis):
        return nivel
    if idade is None:
        novo = _menor(nivel, teto_sem_data, niveis)
        if novo != nivel:
            motivos.append(f"data_desconhecida_teto_{teto_sem_data}")
        return novo
    atual = nivel
    while _idx(atual, niveis) > _idx("BAIXA", niveis) and atual in limites and idade > limites[atual]:
        motivos.append(f"idade_{idade}d_acima_de_{limites[atual]}d_desce_de_{atual}")
        atual = niveis[_idx(atual, niveis) - 1]
    return atual


# ----------------------------------------------------------------------------
# Resultado
# ----------------------------------------------------------------------------

@dataclass
class ResultadoCriticidade:
    modulo: str
    nivel: str
    prioridade: Optional[str]
    pontuacao: float                 # desempate dentro do módulo (M9A: reforços*25; M8: gravidade/11*100)
    idade_dias: Optional[int]
    objeto: Optional[str] = None
    fase: Optional[str] = None
    reforcos: List[str] = field(default_factory=list)
    motivos: List[str] = field(default_factory=list)
    avaliavel: bool = True
    selecionavel: bool = False
    versao_regra: str = VERSAO_REGRA
    versao_parametros: str = ""
    origem_classificacao: str = "tipo_oficial"      # 'tipo_oficial' (SCM/SEMAD estruturado) | 'texto_livre_curado'
    provisoria: bool = False                         # True enquanto não houver tipo oficial estruturado
    nivel_potencial: Optional[str] = None            # CRITICO/ALTA reconhecido, aguardando evidência (estados POTENCIAL_*)
    nivel_antes_idade: Optional[str] = None          # nível antes do corte por atualidade (explica "barrado só pela idade")
    evidencia_suficiente: bool = True
    evidencia_usada: str = ""                        # descrição determinística da evidência que sustentou a classificação
    pendencia: Optional[str] = None                  # o que falta para virar definitiva
    bloqueios: List[str] = field(default_factory=list)  # por que NÃO é selecionável (vazio = selecionável)

    def como_componentes(self) -> dict:
        return {
            "criticidade": self.nivel, "prioridade_derivada": self.prioridade, "pontuacao": self.pontuacao,
            "idade_dias": self.idade_dias, "objeto": self.objeto, "fase": self.fase, "reforcos": self.reforcos,
            "motivos": self.motivos, "avaliavel": self.avaliavel, "selecionavel": self.selecionavel,
            "versao_regra": self.versao_regra, "versao_parametros": self.versao_parametros, "modulo": self.modulo,
            "origem_classificacao": self.origem_classificacao, "provisoria": self.provisoria,
            "nivel_potencial": self.nivel_potencial, "nivel_antes_idade": self.nivel_antes_idade,
            "evidencia_suficiente": self.evidencia_suficiente, "evidencia_usada": self.evidencia_usada,
            "pendencia": self.pendencia, "bloqueios": self.bloqueios,
        }

    def resumo_motivos(self) -> str:
        return ";".join(self.motivos)


def _finalizar(res: ResultadoCriticidade, par: dict) -> ResultadoCriticidade:
    res.prioridade = par["prioridade_derivada"].get(res.nivel)
    bl = []
    if not res.avaliavel:
        bl.append("nao_avaliavel")
    if res.nivel in (ESTADO_POTENCIAL_CRITICO, ESTADO_POTENCIAL_ALTA):
        bl.append("pendente_de_evidencia")
    elif res.nivel not in par["piso_selecao"] and res.avaliavel:
        bl.append("abaixo_do_piso")
    if not res.evidencia_suficiente and "pendente_de_evidencia" not in bl:
        bl.append("evidencia_insuficiente")
    if res.provisoria:
        bl.append("classificacao_provisoria")
    res.bloqueios = bl
    res.selecionavel = not bl
    res.versao_parametros = par["versao_parametros"]
    res.versao_regra = par.get("versao_regra", VERSAO_REGRA)
    return res


# ----------------------------------------------------------------------------
# M9A
# ----------------------------------------------------------------------------

def _numero_pt(txt: str) -> Optional[float]:
    """'1.852,42' -> 1852.42 ; '688,08' -> 688.08 ; '71,71' -> 71.71 ; '1096.57' -> 1096.57"""
    t = txt.strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def area_de_texto(*textos: Optional[str]) -> Optional[float]:
    """Maior valor 'N ha / hectares' citado em texto livre (usado só para casos curados, que não têm o campo
    de área estruturado do SCM)."""
    melhor = None
    for t in textos:
        for m in re.finditer(r"(\d[\d.,]*)\s*(?:ha\b|hectares?)", t or "", flags=re.IGNORECASE):
            v = _numero_pt(m.group(1))
            if v is not None and (melhor is None or v > melhor):
                melhor = v
    return melhor


def _propostos_ativos(par9: dict) -> bool:
    return bool(par9.get("usar_objetos_propostos"))


def _fase(tokens: List[str], texto_livre: bool, par9: dict) -> str:
    if _contem(tokens, par9["fase_negativa"]):
        return "negativa"
    if _contem(tokens, par9["fase_pedido"]):
        return "pedido"
    marcadores = list(par9["fase_efetiva_texto_livre"] if texto_livre else par9["fase_efetiva"])
    if _propostos_ativos(par9):
        marcadores += list(par9.get("fase_efetiva_adicional_propostos", []))
    if _contem(tokens, marcadores):
        return "efetiva"
    return "indefinida"


def _objeto(tokens: List[str], par9: dict) -> str:
    for item in par9["objetos"]:
        if _contem(tokens, item["palavras"]):
            return item["objeto"]
    if _propostos_ativos(par9):
        for item in par9.get("objetos_propostos", []):
            if _contem(tokens, item["palavras"]):
                return item["objeto"]
    return "outro"


def _nivel_objeto_proposto(objeto: str, tokens: List[str], par9: dict, emp: bool, est: bool, area_ok: bool,
                           area_grande: bool, motivos: List[str]) -> Optional[str]:
    """Nível dos objetos PROPOSTOS (só ativos com usar_objetos_propostos=true). Regra declarada no parâmetro:
    nivel_com_reforco se ALGUMA das reforco_condicoes vale, senão nivel_sem_reforco; desfecho_baixo força o nível sem reforço."""
    for item in par9.get("objetos_propostos", []):
        if item["objeto"] != objeto:
            continue
        cond = {"empresa": emp, "mineral": est, "area_min": area_ok, "area_grande": area_grande}
        com_reforco = any(cond.get(c, False) for c in item.get("reforco_condicoes", []))
        if item.get("desfecho_baixo") and _contem(tokens, item["desfecho_baixo"]):
            motivos.append(f"{objeto}_desfecho_que_mantem_decisao_anterior")
            return item["nivel_sem_reforco"]
        motivos.append(f"{objeto}_{'com' if com_reforco else 'sem'}_reforco")
        return item["nivel_com_reforco"] if com_reforco else item["nivel_sem_reforco"]
    return None


def _classificar_m9a(entrada: dict, par: dict, referencia: date) -> ResultadoCriticidade:
    """`entrada` (todas as chaves opcionais exceto o texto do tipo):
         tipo_scm        nome do tipo no dicionário Evento.txt (DSEvento) — fonte preferida
         tipo_texto      alternativa para casos sem tipo SCM (curados): tipo_evento + decisão em texto livre
         data_ato        data do ato (ISO ou dd/mm/aaaa)
         titular, substancia, area_ha (float ou texto), n_municipios (int)
         tem_evidencia   True se existe evidência/URL oficial do ato
    `referencia` é a data de hoje passada explicitamente (reprodutibilidade)."""
    par9 = par["m9a"]
    niveis = par["niveis"]
    motivos: List[str] = []
    texto_livre = not entrada.get("tipo_scm")
    tokens = normalizar(entrada.get("tipo_scm") or entrada.get("tipo_texto")).split()
    data_ato = _para_data(entrada.get("data_ato"))
    idade = (referencia - data_ato).days if data_ato else None
    titular = normalizar(entrada.get("titular")).split()
    subst = normalizar(entrada.get("substancia") or entrada.get("substancia_texto")).split()
    try:
        area = float(entrada.get("area_ha")) if entrada.get("area_ha") not in (None, "") else 0.0
    except (TypeError, ValueError):
        area = 0.0
    n_mun = int(entrada.get("n_municipios") or 0)

    emp = _contem(titular, par9["empresas_relevantes"])
    est = _contem(subst, par9["minerais_estrategicos"])
    area_ok = area >= par9["area_min_ha"]
    area_grande = area >= par9["area_grande_ha"]
    reforcos = [r for r, ativo in (("empresa_relevante", emp), ("mineral_estrategico", est),
                                   ("area_" + str(int(par9["area_min_ha"])) + "ha", area_ok),
                                   ("varios_municipios", n_mun >= 2)) if ativo]
    pontuacao = float(len(reforcos) * 25)

    # P2 — rotina anula tudo (checada ANTES de qualquer outro gatilho)
    if _contem(tokens, par9["rotina"]):
        motivos.append("rotina_anula_gatilhos")
        res = ResultadoCriticidade("M9A", "ROTINA", "D", 0.0, idade, objeto="rotina", fase=None, motivos=motivos)
        return _finalizar(res, par)

    if not tokens:
        motivos.append("tipo_do_ato_desconhecido_nao_avaliavel")
        res = ResultadoCriticidade("M9A", ESTADO_NAO_AVALIAVEL, None, 0.0, idade, objeto="desconhecido", fase=None,
                                   reforcos=reforcos, motivos=motivos, avaliavel=False)
        return _finalizar(res, par)

    objeto = _objeto(tokens, par9)
    fase = _fase(tokens, texto_livre, par9)
    motivos.append(f"objeto={objeto}")
    motivos.append(f"fase={fase}")
    if texto_livre:
        motivos.append("classificado_por_texto_livre_sem_tipo_scm")
        motivos.append("classificacao_provisoria_origem_curada")

    lavra = _contem(tokens, par9["marcadores_lavra"])

    # P1 — pedido/protocolo e fase negativa nunca passam de BAIXA
    if fase in ("pedido", "negativa"):
        nivel = "BAIXA"
        motivos.append("pedido_nunca_vale_como_ato_efetivado" if fase == "pedido" else "ato_negativo_teto_BAIXA")
    else:
        if objeto == "perda_titulo":
            nivel = "CRITICO" if lavra else "ALTA"
            motivos.append("perda_de_titulo_de_lavra" if lavra else "perda_de_titulo_de_pesquisa")
        elif objeto == "prorrogacao_prazo_requerer_lavra":
            # Pedido já ficou em BAIXA (P1). Decisão concedendo + recente = consequência material (preserva a janela
            # para requerer a lavra). Decisão antiga ou sem marcador de decisão = BAIXA. Empresa, mineral e área
            # entram só como reforço (pontuação/desempate), nunca como gatilho principal.
            pl = par9["prorrogacao_prazo_lavra"]
            if fase == "efetiva" and idade is not None and idade <= pl["atualidade_dias_recente"]:
                nivel = pl["nivel_decisao_recente"]
                motivos.append("prorrogacao_prazo_lavra_decisao_recente")
            else:
                nivel = pl["nivel_decisao_antiga"]
                motivos.append("prorrogacao_prazo_lavra_decisao_antiga_ou_sem_data" if fase == "efetiva"
                               else "prorrogacao_prazo_lavra_fase_nao_efetiva")
        elif objeto == "gravame":
            nivel = "ALTA" if (emp or est) else "MEDIA"
            motivos.append("gravame_com_reforco" if (emp or est) else "gravame_sem_reforco")
        elif objeto == "cessao":
            if (emp and est) or (est and area_grande):
                nivel = "ALTA"
            elif emp or est or area_ok:
                nivel = "MEDIA"
            else:
                nivel = "BAIXA"
        elif objeto == "autorizacao_extracao":
            nivel = "ALTA" if (area_ok or emp or est) else "MEDIA"
        elif objeto == "renuncia":
            nivel = "MEDIA" if (emp or est) else "BAIXA"
        elif objeto == "relatorio_aprovado":
            nivel = "MEDIA" if (emp or est or area_ok) else "BAIXA"
        elif objeto == "alvara_outorga":
            nivel = "MEDIA" if (emp or est) else "BAIXA"
        elif objeto == "servidao":
            nivel = "MEDIA" if emp else "BAIXA"
        else:  # edital_disponibilidade, outro (e, se ativados, os objetos propostos)
            proposto = _nivel_objeto_proposto(objeto, tokens, par9, emp, est, area_ok, area_grande, motivos) \
                if objeto != "outro" and objeto != "edital_disponibilidade" else None
            nivel = proposto or "BAIXA"
        if fase == "indefinida" and _idx(nivel, niveis) > _idx(par9["teto_fase_indefinida"], niveis):
            nivel = par9["teto_fase_indefinida"]
            motivos.append(f"fase_indefinida_teto_{nivel}")

    nivel_antes_idade = nivel
    nivel = _aplicar_idade(nivel, idade, par9["atualidade_dias"], par9["teto_sem_data"], niveis, motivos)
    tem_ev = bool(entrada.get("tem_evidencia"))
    potencial = None
    if not tem_ev and _idx(nivel, niveis) > _idx(par9["teto_sem_evidencia"], niveis):
        # Falta de evidência NÃO rebaixa em silêncio: o caso que a régua reconhece como ALTA/CRITICO vira estado
        # intermediário, fora da fila e da IA, até a evidência estruturada chegar.
        potencial = nivel
        nivel = par9.get("pendencia_evidencia", {}).get("estado_por_nivel", {
            "CRITICO": ESTADO_POTENCIAL_CRITICO, "ALTA": ESTADO_POTENCIAL_ALTA})[potencial]
        motivos.append(f"potencial_{potencial}_aguarda_evidencia_estruturada")
    elif not tem_ev:
        motivos.append("sem_evidencia_estruturada_nao_selecionavel")
    res = ResultadoCriticidade("M9A", nivel, "D", pontuacao, idade, objeto=objeto, fase=fase,
                               reforcos=reforcos, motivos=motivos)
    res.nivel_potencial = potencial
    res.nivel_antes_idade = nivel_antes_idade
    res.evidencia_suficiente = tem_ev
    if not tem_ev:
        res.pendencia = "evidencia_estruturada"
    if texto_livre:
        res.origem_classificacao, res.provisoria = par9.get("origem_curada", ORIGEM_CURADA), True
        res.pendencia = ("tipo_oficial_e_evidencia_estruturada" if not tem_ev else "tipo_oficial_scm")
    return _finalizar(res, par)


# ----------------------------------------------------------------------------
# M8
# ----------------------------------------------------------------------------

def _classificar_m8(entrada: dict, par: dict, referencia: date) -> ResultadoCriticidade:
    """`entrada`:
         status_processamento  'processado' | 'falha_extracao' | 'descartado' ...
         faixa_vinculo         'confirmado' | 'provavel' | 'contextual' | 'descartado'
         data_ocorrencia       data da ocorrência (ISO ou dd/mm/aaaa) ou None
         confirmados           dict de fatos CONFIRMADOS em campo estruturado (True/None):
                               vitimas, risco_estrutura, risco_abastecimento, atingiu_curso_agua,
                               saiu_limite_operacao, rejeito_ou_perigoso, atuacao_orgao_publico
         sinais_textuais       dict de sinais de PALAVRA-CHAVE (não verificados): curso_dagua, rejeito,
                               risco_estrutural, vitimas, ...
         score_gravidade       nota de gravidade do SCORE-M8-V1.0 (0-11) — só desempate
         tem_evidencia         True se o comunicado oficial foi lido"""
    par8 = par["m8"]
    niveis = par["niveis"]
    motivos: List[str] = []
    data_oc = _para_data(entrada.get("data_ocorrencia"))
    idade = (referencia - data_oc).days if data_oc else None
    try:
        grav = float(entrada.get("score_gravidade")) if entrada.get("score_gravidade") is not None else 0.0
    except (TypeError, ValueError):
        grav = 0.0
    pontuacao = round(grav / 11.0 * 100, 2)

    if entrada.get("status_processamento") == "falha_extracao" or not entrada.get("tem_evidencia", True):
        # NÃO é ROTINA: o texto oficial não foi lido, então não há julgamento editorial possível.
        motivo_falha = str(entrada.get("motivo_falha") or "")
        if motivo_falha.startswith("limite"):
            motivos.append("nao_avaliavel_documento_nao_aberto_por_limite_de_requisicoes")
        elif entrada.get("status_processamento") == "falha_extracao":
            motivos.append("nao_avaliavel_falha_de_extracao")
        else:
            motivos.append("nao_avaliavel_sem_evidencia_suficiente")
        res = ResultadoCriticidade("M8", ESTADO_NAO_AVALIAVEL, None, 0.0, idade, objeto="nao_avaliavel", fase=None,
                                   motivos=motivos, avaliavel=False)
        return _finalizar(res, par)

    vinculo = entrada.get("faixa_vinculo")
    if vinculo not in par8["faixas_vinculo_validas"]:
        motivos.append(f"vinculo_{vinculo}_insuficiente")
        res = ResultadoCriticidade("M8", "ROTINA", "D", 0.0, idade, objeto="sem_vinculo", fase=None, motivos=motivos)
        return _finalizar(res, par)

    conf = entrada.get("confirmados") or {}
    txt = entrada.get("sinais_textuais") or {}
    fato_fatal = bool(conf.get("vitimas") or conf.get("risco_estrutura") or conf.get("risco_abastecimento"))
    fato_ambiental = bool(conf.get("atingiu_curso_agua") or
                          (conf.get("saiu_limite_operacao") and conf.get("rejeito_ou_perigoso")) or
                          conf.get("atuacao_orgao_publico"))
    sinal_textual = any(bool(v) for v in txt.values())
    agravante_so_textual = False

    if fato_fatal:
        nivel = "CRITICO"
        motivos.append("fato_grave_confirmado")
    elif fato_ambiental:
        nivel = "ALTA"
        motivos.append("impacto_ambiental_confirmado")
    elif sinal_textual:
        nivel = "MEDIA"
        agravante_so_textual = True
        motivos.append("agravante_apenas_textual_nao_verificado")
    else:
        nivel = "BAIXA"
        motivos.append("sem_agravante")
    if vinculo == "provavel":
        motivos.append("vinculo_provavel")
        if _idx(nivel, niveis) > _idx(par8["teto_vinculo_provavel"], niveis):
            nivel = par8["teto_vinculo_provavel"]
            motivos.append(f"vinculo_provavel_teto_{nivel}")

    nivel_antes_idade = nivel
    nivel = _aplicar_idade(nivel, idade, par8["atualidade_dias"], par8["teto_sem_data"], niveis, motivos)
    res = ResultadoCriticidade("M8", nivel, "D", pontuacao, idade, objeto="acidente_ambiental",
                               fase=vinculo, reforcos=sorted(k for k, v in txt.items() if v), motivos=motivos)
    res.nivel_antes_idade = nivel_antes_idade
    if agravante_so_textual and nivel == "MEDIA" and par8.get("agravante_textual_provisorio", True):
        # MEDIA sustentada só por palavra-chave do texto: provisória até haver confirmação estruturada do agravante.
        # Texto livre NUNCA sobe o caso para ALTA/CRITICO.
        res.provisoria = True
        res.origem_classificacao = par8.get("origem_agravante_textual", "agravante_por_palavra_chave")
        res.pendencia = "confirmacao_estruturada_do_agravante"
        motivos.append("classificacao_provisoria_agravante_nao_confirmado_em_campo_estruturado")
    return _finalizar(res, par)


def _com_evidencia_usada(res: ResultadoCriticidade, entrada: dict) -> ResultadoCriticidade:
    """Registra QUAL evidência sustentou a classificação (texto determinístico passado pela origem da entrada; na falta
    dele, uma descrição genérica do que a régua efetivamente consultou)."""
    texto = entrada.get("evidencia_usada")
    if not texto:
        if res.nivel == ESTADO_NAO_AVALIAVEL:
            texto = "nenhuma: texto oficial não lido"
        elif entrada.get("tem_evidencia", True):
            texto = "evidência oficial estruturada (detalhe não informado pela origem)"
        else:
            texto = "nenhuma linha de evidência estruturada"
    res.evidencia_usada = texto
    return res


def classificar_m9a(entrada: dict, par: dict, referencia: date) -> ResultadoCriticidade:
    return _com_evidencia_usada(_classificar_m9a(entrada, par, referencia), entrada)


def classificar_m8(entrada: dict, par: dict, referencia: date) -> ResultadoCriticidade:
    return _com_evidencia_usada(_classificar_m8(entrada, par, referencia), entrada)


def classificar(modulo: str, entrada: dict, par: dict, referencia: date) -> ResultadoCriticidade:
    if modulo == "M9A":
        return classificar_m9a(entrada, par, referencia)
    if modulo == "M8":
        return classificar_m8(entrada, par, referencia)
    raise ValueError(f"módulo sem régua de criticidade: {modulo}")


# ----------------------------------------------------------------------------
# Grupos de seleção (derivados por regra; nunca preenchidos à mão)
# ----------------------------------------------------------------------------

SELECIONAVEL_AGORA = "SELECIONAVEL_AGORA"
PENDENTE_DE_EVIDENCIA = "PENDENTE_DE_EVIDENCIA"
NAO_AVALIAVEL = "NAO_AVALIAVEL"
FORA_DA_SELECAO = "FORA_DA_SELECAO"
GRUPOS_SELECAO = (SELECIONAVEL_AGORA, PENDENTE_DE_EVIDENCIA, NAO_AVALIAVEL, FORA_DA_SELECAO)
_STATUS_FORA_DE_ESCOPO = ("descartado", "publicado", "pronto_para_publicar")


def grupo_selecao(res: "ResultadoCriticidade", par: dict, status_editorial: Optional[str] = None,
                  ia_sucesso: bool = False) -> tuple:
    """Grupo de seleção do evento e o motivo, derivados SÓ da classificação vigente e do estado do evento. A mesma
    regra existe em SQL (public.criticidade_grupo_selecao, usada pela view v_criticidade_selecao); os testes comparam
    as duas. Ordem de avaliação:
      1. NAO_AVALIAVEL                      -> NAO_AVALIAVEL
      2. IA já concluiu com sucesso          -> FORA_DA_SELECAO (não disputa vaga de caso novo)
      3. descartado/publicado/pronto         -> FORA_DA_SELECAO
      4. somente_novos e status não-novo     -> FORA_DA_SELECAO (já em fluxo editorial)
      5. POTENCIAL_* ou (nível >= piso, avaliável, e provisória ou sem evidência suficiente) -> PENDENTE_DE_EVIDENCIA
      6. nível >= piso, avaliável, evidência suficiente, não provisória, sem bloqueios        -> SELECIONAVEL_AGORA
      7. demais (BAIXA, ROTINA)              -> FORA_DA_SELECAO"""
    sel = par["selecao"]
    if res.nivel == ESTADO_NAO_AVALIAVEL:
        return NAO_AVALIAVEL, ";".join(res.motivos)
    if sel.get("exclui_ja_analisado_ia", True) and ia_sucesso:
        return FORA_DA_SELECAO, "ja_analisado_pela_ia_com_sucesso"
    if status_editorial in _STATUS_FORA_DE_ESCOPO:
        return FORA_DA_SELECAO, f"status_editorial_{status_editorial}"
    if sel.get("somente_novos", True) and status_editorial not in sel.get("status_editorial_novos", []):
        return FORA_DA_SELECAO, f"ja_em_fluxo_editorial_status_{status_editorial}_(fora_dos_novos)"
    potencial = res.nivel in (ESTADO_POTENCIAL_CRITICO, ESTADO_POTENCIAL_ALTA)
    no_piso = res.nivel in par["piso_selecao"] and res.avaliavel
    if potencial or (no_piso and (res.provisoria or not res.evidencia_suficiente)):
        return PENDENTE_DE_EVIDENCIA, ";".join(res.bloqueios)
    if no_piso and res.evidencia_suficiente and not res.provisoria and not res.bloqueios:
        return SELECIONAVEL_AGORA, "criticidade_consolidada_com_evidencia"
    return FORA_DA_SELECAO, f"abaixo_do_piso_{res.nivel}"


# ----------------------------------------------------------------------------
# Seleção determinística
# ----------------------------------------------------------------------------

def chave_ordenacao(c: dict, niveis: Sequence[str] = _NIVEIS_PADRAO) -> tuple:
    """criticidade > prioridade > pontuação > atualidade (mais recente primeiro) > qualidade da evidência >
    chave estável. `c` tem: nivel, prioridade, pontuacao, idade_dias, qualidade_evidencia, id_evento."""
    idade = c.get("idade_dias")
    nivel_ord = c.get("nivel_potencial") or c["nivel"]  # pendentes de evidência ordenam pelo nível que teriam
    return (-(list(niveis).index(nivel_ord) if nivel_ord in niveis else -1), "ABCD".index(c["prioridade"]) if c.get("prioridade") else 4, -float(c.get("pontuacao") or 0.0),
            idade if idade is not None else 10 ** 9, -int(c.get("qualidade_evidencia") or 0), c["id_evento"])


def selecionar(candidatos: List[dict], par: dict, limite: Optional[int] = None) -> dict:
    """Entre os candidatos ELEGÍVEIS da rodada (já sem os já analisados), mantém só os de nível >= piso,
    ordena pela chave determinística e devolve a lista escolhida, o primeiro excluído por corte de limite e
    os que ficaram imediatamente abaixo do corte (por piso ou por limite)."""
    limite = limite if limite is not None else par["limite_selecao_padrao"]
    niveis = par["niveis"]
    aptos = [c for c in candidatos if c["nivel"] in par["piso_selecao"] and c.get("avaliavel", True)
             and c.get("evidencia_suficiente", True) and not c.get("provisoria", False)
             and not c.get("ja_analisado_ia", False)]
    aptos.sort(key=lambda c: chave_ordenacao(c, niveis))
    escolhidos = aptos[:limite]
    cortados_por_limite = aptos[limite:]
    abaixo_piso = sorted([c for c in candidatos if c not in aptos], key=lambda c: chave_ordenacao(c, niveis))
    return {"escolhidos": escolhidos, "cortados_por_limite": cortados_por_limite, "abaixo_do_piso": abaixo_piso}
