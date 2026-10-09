"""
Roteamento de fontes (versionado). O Radar NÃO deixa a IA pesquisar a internet: a coleta usa somente
(1) fontes cadastradas, (2) URLs aprovadas nas Cartas Operacionais, (3) links/documentos encontrados
DENTRO dessas fontes oficiais e (4) fontes complementares previstas para o módulo.

Hierarquia: a fonte complementar nunca substitui o ato primário; a consulta estruturada do M6 não
substitui a descoberta diária; notícia (M7) só enriquece.
"""
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

VERSAO_ROTAS = "ROTAS-V1"

ROTAS: Dict[str, dict] = {
    "M6": {
        "descoberta": ["https://outorga.meioambiente.mg.gov.br/index.php?r=portaria/listar"],
        "estruturada": ["https://sistemas.meioambiente.mg.gov.br/licenciamento/site/lista-outorgas"],
        "complementares": ["Diário Oficial de Minas Gerais", "página individual da outorga", "parecer", "certificado",
                            "extrato", "licenciamento ambiental", "TAC", "autos relacionados"],
        "regras": ["consulta estruturada NÃO substitui a descoberta diária",
                   "ausência na consulta estruturada não invalida ato localizado em outra fonte oficial"],
    },
    "M7": {
        "descoberta": ["https://sistemas.meioambiente.mg.gov.br/reunioes/"],
        "estruturada": [],
        "complementares": ["pauta", "parecer", "pedido de vista", "retirada", "diligência", "votação", "decisão", "ata",
                            "certificado", "licença/ato autorizativo relacionado"],
        "regras": ["notícia institucional ou empresarial é somente enriquecimento; nunca substitui decisão oficial"],
    },
    "M8": {
        "descoberta": ["https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026"],
        "estruturada": [],
        "complementares": ["página individual do comunicado", "documento/comunicado associado"],
        "regras": ["a página anual descobre o caso; depois abrir a página individual e o documento associado",
                   "nunca classificar o acidente somente pelo título ou município"],
    },
    "M9A": {
        "descoberta": ["https://dadosabertos.anm.gov.br/SCM/microdados/"],
        "estruturada": ["https://www.gov.br/anm/pt-br/acesso-a-informacao/dados-abertos/bases-de-dados"],
        "confirmacao": ["https://dadosabertos.anm.gov.br/SIGMINE/PROCESSOS_MINERARIOS/"],
        "complementares": ["https://www.in.gov.br/", "https://sistemas.meioambiente.mg.gov.br/licenciamento/",
                            "SEI/ANM", "processo judicial", "documentos ambientais oficiais", "manifestação oficial da empresa"],
        "regras": ["SCM descobre; SIGMINE confirma atributos espaciais; DOU/SEI/documentos aprofundam",
                   "fonte complementar nunca substitui o ato primário"],
    },
    "M9B": {
        "descoberta": ["https://dadosabertos.anm.gov.br/SIGBM/"],
        "estruturada": ["https://app.anm.gov.br/SIGBM/Publico"],
        "confirmacao": ["https://www.gov.br/anm/pt-br/assuntos/barragens/dce-e-dco",
                         "https://www.gov.br/anm/pt-br/assuntos/barragens/boletim-de-barragens-de-mineracao"],
        "complementares": ["https://www.gov.br/anm/pt-br/assuntos/barragens/legislacao/resolucao-no-95-2022.pdf"],
        "regras": ["Barragens.csv gera o sinal; para prioridade A, B e ausências buscar confirmação oficial",
                   "ausência no CSV NÃO significa descaracterização, eliminação física ou encerramento"],
    },
}

# Domínios oficiais onde links/documentos encontrados DENTRO das fontes podem ser abertos.
# (host exato ou sufixo com ponto). Qualquer outro host = fora da rota (não é aberto).
HOSTS_OFICIAIS: Tuple[str, ...] = (
    "meioambiente.mg.gov.br",            # inclui sistemas., outorga., transparencia., ecosistemas.
    "dadosabertos.anm.gov.br",
    "app.anm.gov.br",
    "sigbm.anm.gov.br",
    "www.gov.br",                        # só o caminho /anm/ (ver CAMINHOS_RESTRITOS)
    "in.gov.br",                         # DOU
    "jornalminasgerais.mg.gov.br",
    "iof.mg.gov.br",
)
# gov.br é amplo: só o caminho /anm/ é aprovado nas Cartas.
CAMINHOS_RESTRITOS = {"www.gov.br": ("/anm/",)}


def modulos() -> List[str]:
    return sorted(ROTAS)


def rota_do_modulo(modulo: str) -> dict:
    if modulo not in ROTAS:
        raise KeyError(f"módulo sem rota cadastrada: {modulo}")
    return ROTAS[modulo]


def descricao_da_rota(modulo: str) -> dict:
    """Registro da rota escolhida (vai para o log da execução ANTES de qualquer requisição)."""
    r = rota_do_modulo(modulo)
    return {"versao_rotas": VERSAO_ROTAS, "modulo": modulo,
            "fonte_primaria": r["descoberta"], "estruturada": r.get("estruturada", []),
            "confirmacao": r.get("confirmacao", []), "complementares": r.get("complementares", [])}


def url_permitida(url: str) -> Tuple[bool, str]:
    """(ok, motivo). Só http/https, host na lista oficial e, onde houver restrição, caminho aprovado."""
    try:
        p = urlparse(url)
    except ValueError:
        return False, "url_invalida"
    if p.scheme not in ("http", "https") or not p.hostname:
        return False, "esquema_ou_host_invalido"
    host = p.hostname.lower()
    for permitido in HOSTS_OFICIAIS:
        if host == permitido or host.endswith("." + permitido):
            restr = CAMINHOS_RESTRITOS.get(host)
            if restr and not any((p.path or "/").startswith(c) for c in restr):
                return False, f"caminho_nao_aprovado_em_{host}"
            return True, "ok"
    return False, f"host_fora_das_fontes_oficiais:{host}"


def fonte_primaria_url(modulo: str) -> str:
    return rota_do_modulo(modulo)["descoberta"][0]
