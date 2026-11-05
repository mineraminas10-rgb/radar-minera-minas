"""Shared Carta v1.1 editorial discovery filter.

This filter does not calculate the weighted score or 12-item checklist, infer
causality, or publish. Default mode is shadow so results can be audited before
they affect queue eligibility.
"""
from __future__ import annotations
import re
import unicodedata
from typing import Any, Mapping

VERSAO_REGRA = "CARTA-DESCOBERTA-1.1"
MODO_PADRAO = "shadow"
ATIVIDADE = (
    "mineração", "atividade minerária", "empreendimento minerário", "extração mineral",
    "pesquisa mineral", "prospecção mineral", "beneficiamento mineral", "tratamento de minério",
    "cava da mina", "barragem de rejeitos", "pilha de estéril", "bacia de sedimentação",
    "drenagem ácida de mina", "lavra a céu aberto", "lavra subterrânea", "duto de polpa",
    "espodumênio", "minério de ferro", "bauxita", "manganês", "ouro", "lítio", "terras raras",
)
CNAES = ("07103", "07294", "081")
PORTAS_TEXTO = {
    "P1_DANO_OU_RISCO_AMBIENTAL": ("contaminação", "poluição", "assoreamento", "turbidez", "vazamento", "rejeitos", "erosão", "drenagem ácida", "aquífero", "lençol freático", "metais pesados", "arsênio", "chumbo", "cádmio", "cianeto", "mercúrio", "supressão vegetal", "desmatamento", "fauna", "flora", "cavidade", "poeira", "emissão atmosférica", "material particulado", "ruído", "vibração"),
    "P2_VIDA_SAUDE_SEGURANCA_OU_COMUNIDADE": ("comunidade", "morador", "trabalhador", "terceirizado", "vítima", "ferido", "hospitalização", "morte", "óbito", "evacuação", "reassentamento", "saúde pública", "escola", "abastecimento", "poço artesiano", "cisterna", "captação comunitária", "pescadores", "agricultores", "potabilidade", "dessedentação de animais"),
    "P3_SEGURANCA_DE_ESTRUTURA": ("barragem", "pilha", "dique", "cava", "anomalia", "trinca", "instabilidade", "risco de ruptura", "nível de emergência", "sirene", "extravasamento", "rompimento", "desabamento", "colapso"),
    "P4_DECISAO_REGULATORIA_MATERIAL": ("decisão", "julgamento", "licença", "licenciamento", "outorga", "portaria", "parecer", "ata", "recurso", "condicionante", "tac", "termo de compromisso", "autorização", "concessão", "indeferimento", "deferimento"),
    "P5_SANCAO_EMBARGO_INTERDICAO_OU_PERDA_DE_DIREITO": ("auto de infração", "multa", "embargo", "interdição", "suspensão", "cassação", "revogação", "anulação", "sanção", "apreensão", "perdimento", "perda de direito"),
    "P6_MUDANCA_OPERACIONAL_MATERIAL": ("paralisação", "retomada", "fechamento", "desmobilização", "redução de produção", "aumento de produção", "mudança operacional", "interrupção da operação"),
    "P7_INVESTIMENTO_EXPANSAO_OU_INFRAESTRUTURA": ("investimento", "expansão", "ampliação", "implantação", "capacidade", "produção", "mineroduto", "ferrovia", "terminal", "linha de transmissão", "infraestrutura", "financiamento", "aquisição", "venda", "fusão", "incorporação"),
    "P9_CRUZAMENTO_REINCIDENCIA_OU_PADRAO": ("reincidência", "reincidente", "reiterado", "repetição de ocorrências", "casos relacionados", "padrão recorrente"),
    "P10_INTERESSE_PUBLICO_TERRITORIAL_OU_POLITICO": ("conflito territorial", "terra indígena", "território quilombola", "unidade de conservação", "desapropriação", "servidão", "patrimônio cultural", "patrimônio histórico", "audiência pública", "interesse público", "acesso interrompido", "estrada bloqueada"),
}
PORTAS_ESTRUTURADAS = {
    "P8_ENTIDADE_PROJETO_OU_ATIVO_ESTRATEGICO": ("empresa_watchlist", "ativo_watchlist", "projeto_estrategico"),
    "P9_CRUZAMENTO_REINCIDENCIA_OU_PADRAO": ("reincidencia_confirmada", "casos_relacionados"),
    "P11_ANTECEDENCIA_OU_EXCLUSIVIDADE": ("antecedencia_relevante", "exclusividade_jornalistica"),
    "P12_ATUALIZACAO_MATERIAL_DE_CASO": ("atualizacao_material",),
}
VINCULOS_OFICIAIS = ("processo_anm", "identificador_sigbm", "cnpj_watchlist_confirmado", "empresa_watchlist_confirmada", "ativo_watchlist_confirmado", "atividade_licenciada_mineraria", "vinculo_oficial_confirmado", "empresa_watchlist", "ativo_watchlist", "projeto_estrategico")
NEGACOES = ("não houve", "não ocorreu", "não foi constatado", "não foi constatada", "não foi identificada", "sem registro de", "ausência de", "não se verificou", "inexistência de")
ALEGACOES = ("alega que", "denuncia que", "segundo moradores", "investiga possível", "suspeita de")
RISCOS = ("risco de", "possibilidade de", "potencial de", "pode ocorrer", "ameaça de")
PEDIDOS = ("pedido de", "requerimento de", "solicitação de", "solicitou", "protocolou pedido")
DECISOES_NEGATIVAS = ("indeferiu", "negou o pedido", "não concedeu", "cancelou", "revogou", "anulou")
ATOS_EFETIVADOS = ("deferiu", "concedeu", "autorizou", "aprovou", "publicou", "embargou", "interditou", "cassou")

def normalizar(valor: Any) -> str:
    s = unicodedata.normalize("NFKD", str(valor or ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)).casefold()).strip()

def _match(texto: str, termo: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(normalizar(termo))}(?!\w)", normalizar(texto)))

def _frases(texto: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", texto or "") if s.strip()]

def _semantica(texto: str) -> str:
    frases = [normalizar(s) for s in _frases(texto)]
    if not frases: return "AUSENCIA_DE_INFORMACAO"
    for marcadores, rotulo in ((NEGACOES, "NEGATIVA_EXPLICITA"), (ALEGACOES, "ALEGACAO_OU_INVESTIGACAO"), (RISCOS, "RISCO_OU_POSSIBILIDADE"), (DECISOES_NEGATIVAS, "DECISAO_NEGATIVA"), (PEDIDOS, "PEDIDO_AINDA_NAO_DECIDIDO"), (ATOS_EFETIVADOS, "ATO_OU_DECISAO_EFETIVADA")):
        if any(normalizar(m) in f for f in frases for m in marcadores): return rotulo
    return "SINAL_SEM_STATUS_CONCLUSIVO"

def avaliar_descoberta(evento: Mapping[str, Any], *, modo: str = MODO_PADRAO) -> dict[str, Any]:
    if modo not in {"shadow", "enforce"}: raise ValueError("modo deve ser shadow ou enforce")
    campos = ("titulo", "titulo_fato", "metadados", "texto_documento", "texto_fiscal", "descricao_evento", "tipo_evento", "ementa", "trecho_literal")
    texto = "\n".join(str(evento.get(k) or "") for k in campos)
    atividade = [t for t in ATIVIDADE if _match(texto, t)]
    cnae_digitos = re.sub(r"\D", "", str(evento.get("cnae") or evento.get("cnae_empreendedor") or ""))
    cnae = next((x for x in CNAES if cnae_digitos.startswith(x)), None)
    evid_vinc = ([{"tipo":"termo_setorial","valor":t} for t in atividade] + ([{"tipo":"cnae","valor":cnae}] if cnae else []))
    for campo in VINCULOS_OFICIAIS:
        valor = evento.get(campo)
        if valor is not None and valor is not False and valor != "": evid_vinc.append({"tipo":campo,"valor":valor})
    direto = bool(evid_vinc)
    contextuais = evento.get("evidencias_contextuais") or []
    tipos_contextuais = {str(e.get("tipo")) for e in contextuais if isinstance(e, Mapping) and e.get("tipo") and e.get("valor")}
    contextual = not direto and len(tipos_contextuais) >= 2
    portas = {}
    for nome, termos in PORTAS_TEXTO.items():
        sinais = []
        for frase in _frases(texto):
            frase_n = normalizar(frase)
            for termo in termos:
                if not _match(frase, termo): continue
                natureza = "NEGATIVA_EXPLICITA" if nome != "P4_DECISAO_REGULATORIA_MATERIAL" and any(normalizar(n) in frase_n for n in NEGACOES) else "ALEGACAO_OU_INVESTIGACAO" if any(normalizar(m) in frase_n for m in ALEGACOES) else "RISCO_OU_POSSIBILIDADE" if any(normalizar(m) in frase_n for m in RISCOS) else "SINAL_TEXTUAL_SEM_CONFIRMAR_CAUSALIDADE"
                if natureza != "NEGATIVA_EXPLICITA": sinais.append({"termo":termo,"natureza":natureza,"trecho":frase})
        if sinais: portas[nome] = sinais
    novidade = any(evento.get(k) is True for k in ("novo_ou_alterado","evento_novo","fato_novo"))
    for nome, campos_porta in PORTAS_ESTRUTURADAS.items():
        sinais = []
        for campo in campos_porta:
            valor = evento.get(campo)
            if valor is None or valor is False or valor == "" or valor == []: continue
            if nome.startswith("P8_") and not novidade: continue
            sinais.append({"termo":campo,"natureza":"CAMPO_ESTRUTURADO","trecho":str(valor)})
        if sinais: portas.setdefault(nome, []).extend(sinais)
    presente = bool(texto.strip() or evento.get("documento_url"))
    if not presente: resultado, motivo = "NAO_AVALIAVEL", "documento_ou_conteudo_ausente"
    elif not (direto or contextual): resultado, motivo = "FORA_DO_ESCOPO", "vinculo_minerario_nao_comprovado"
    elif portas: resultado, motivo = ("CLASSIFICAR_AGORA" if direto else "PENDENTE_DE_EVIDENCIA"), "porta_editorial_ativada"
    elif evento.get("ato_rotineiro_inequivoco") is True: resultado, motivo = "ROTINA", "ato_rotineiro_confirmado"
    elif any(evento.get(k) for k in ("empresa_watchlist","ativo_watchlist","projeto_estrategico")): resultado, motivo = "MONITORAMENTO_ESTRATEGICO", "watchlist_sem_fato_novo_ou_porta"
    else: resultado, motivo = "PENDENTE_DE_EVIDENCIA", "nenhuma_porta_identificada"
    return {
        "versao_regra":VERSAO_REGRA,"modo":modo,"resultado_pre_filtro":resultado,"motivo":motivo,
        "vinculo_minerario":"DIRETO" if direto else "CONTEXTUAL" if contextual else "NAO_COMPROVADO",
        "evidencias_vinculo":evid_vinc or list(contextuais),"portas_editoriais_ativadas":portas,
        "semantica_evento":_semantica(texto),"documento_presente":presente,
        "requer_revisao_humana":resultado in {"NAO_AVALIAVEL","PENDENTE_DE_EVIDENCIA","MONITORAMENTO_ESTRATEGICO"} or any(s["natureza"] not in {"SINAL_TEXTUAL_SEM_CONFIRMAR_CAUSALIDADE","CAMPO_ESTRUTURADO"} for ss in portas.values() for s in ss),
        "selecionavel_pela_regra":resultado=="CLASSIFICAR_AGORA","score_editorial":None,"checklist_12":None,
        "fonte_url":evento.get("fonte_url"),"documento_url":evento.get("documento_url")
    }
