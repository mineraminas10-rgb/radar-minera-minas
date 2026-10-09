"""
Módulo 9A — ingestão dos microdados SCM (ANM) + filtro de recorte
(Carta M9A §2, §3, §16 ordem de implementação passo 1).

REESCRITO em 28/09/2026 (achado da auditoria do caso 830.649/2020): a
versão anterior deste arquivo assumia um único CSV plano com colunas
como "evento_tipo"/"titular" — isso era uma SUPOSIÇÃO nunca confirmada
(o comentário original dizia isso explicitamente). Baixei uma amostra
real do dump oficial (`dadosabertos.anm.gov.br/SCM/microdados/
microdados-scm.zip`, 198MB, 28/09/2026) e confirmei que o formato real é
um DUMP RELACIONAL — 28 arquivos `;`-delimitados, `ISO-8859-1`, um por
tabela, SEM view/CSV único pronto. As colunas abaixo são as confirmadas
por leitura direta do cabeçalho de cada arquivo real (não suposição):

    Processo.txt         DSProcesso;NRProcesso;NRAnoProcesso;BTAtivo;NRNUP;
                          IDTipoRequerimento;IDFaseProcesso;
                          IDUnidadeAdministrativaRegional;
                          IDUnidadeProtocolizadora;DTProtocolo;DTPrioridade;
                          QTAreaHA
    ProcessoEvento.txt    DSProcesso;IDEvento;DTEvento;OBEvento;DSPublicacaoDOU
    Evento.txt            IDEvento;DSEvento               (dicionário — 2.926 linhas)
    ProcessoMunicipio.txt DSProcesso;IDMunicipio
    Municipio.txt         IDMunicipio;NMMunicipio;SGUF
    ProcessoSubstancia.txt DSProcesso;IDSubstancia;IDTipoUsoSubstancia;
                          IDMotivoEncerramentoSubstancia;DTInicioVigencia;
                          DTFimVigencia
    Substancia.txt        IDSubstancia;NMSubstancia
    ProcessoPessoa.txt    DSProcesso;IDPessoa;IDTipoRelacao;
                          IDTipoResponsabilidadeTecnica;
                          IDTipoRepresentacaoLegal;DTPrazoArrendamento;
                          DTInicioVigencia;DTFimVigencia
    Pessoa.txt            IDPessoa;NRCPFCNPJ;TPPessoa;NMPessoa

`IDEvento` em `ProcessoEvento.txt` é a IDENTIDADE OFICIAL do tipo de
evento (chave estrangeira para `Evento.txt` — confirmado: o mesmo
IDEvento é reutilizado por qualquer processo que tiver aquele mesmo tipo
de ato). `IDTipoRelacao=1` em `ProcessoPessoa.txt` foi confirmado como
"Titular/Requerente" contra o caso 830.649/2020 (a titularidade vigente é
a linha sem `DTFimVigencia` preenchido).

O QUE AINDA NÃO FOI CONFIRMADO (continua sendo suposição, marcado
explicitamente): nomes exatos de todas as colunas de código auxiliares
(`IDTipoUsoSubstancia`, `IDFaseProcesso` etc. — não precisamos delas para
o M9A, só passam batido); se `ProcessoEvento.txt` tem uma UF/estado
próprios ou se a presença em MG só é dedutível via `ProcessoMunicipio` +
`Municipio.SGUF` (assumido aqui, é o único caminho que os arquivos
confirmados permitem); cobertura completa do dicionário `Evento.txt` para
as famílias fora do M9A (§2) e para os sinais de mudança material — só
"guia de utilização"/"portaria"/"alvará" foram checados contra uma
amostra real (ver classificacao_scm.py); os demais continuam por
inferência de palavra-chave.

`ProcessoEvento.txt` sozinho descompacta para ~1,04 GB — carregar tudo de
uma vez em memória com pandas não escala para rodar contra o dump
completo. `carregar_microdados_scm()` aceita tanto um diretório já
descompactado quanto (por enquanto, mais simples) arquivos já recortados/
fatiados previamente — não faz streaming internamente ainda; isso fica
para quando a Rapha definir o volume real por execução (TODO, não
bloqueante para o teste local deste caso).
"""
import os
import pandas as pd
from typing import Optional

# Colunas confirmadas por leitura direta do cabeçalho de cada arquivo real
# (28/09/2026) — ver docstring do módulo.
COLUNAS_POR_ARQUIVO = {
    "Processo.txt": ["DSProcesso", "NRProcesso", "NRAnoProcesso", "BTAtivo", "NRNUP",
                      "IDTipoRequerimento", "IDFaseProcesso", "IDUnidadeAdministrativaRegional",
                      "IDUnidadeProtocolizadora", "DTProtocolo", "DTPrioridade", "QTAreaHA"],
    "ProcessoEvento.txt": ["DSProcesso", "IDEvento", "DTEvento", "OBEvento", "DSPublicacaoDOU"],
    "Evento.txt": ["IDEvento", "DSEvento"],
    "ProcessoMunicipio.txt": ["DSProcesso", "IDMunicipio"],
    "Municipio.txt": ["IDMunicipio", "NMMunicipio", "SGUF"],
    "ProcessoSubstancia.txt": ["DSProcesso", "IDSubstancia", "IDTipoUsoSubstancia",
                                "IDMotivoEncerramentoSubstancia", "DTInicioVigencia", "DTFimVigencia"],
    "Substancia.txt": ["IDSubstancia", "NMSubstancia"],
    "ProcessoPessoa.txt": ["DSProcesso", "IDPessoa", "IDTipoRelacao", "IDTipoResponsabilidadeTecnica",
                            "IDTipoRepresentacaoLegal", "DTPrazoArrendamento", "DTInicioVigencia",
                            "DTFimVigencia"],
    "Pessoa.txt": ["IDPessoa", "NRCPFCNPJ", "TPPessoa", "NMPessoa"],
}

ID_TIPO_RELACAO_TITULAR = 1  # confirmado contra 830.649/2020 (28/09/2026)

# Carta §2 "Fora do M9A" — comparado contra DSEvento (dicionário), não mais
# contra narrativa livre (ver classificacao_scm.py).
FAMILIAS_FORA_DO_ESCOPO = [
    "barragem", "auto de infracao", "multa", "cfem",
    "agua mineral", "fiscalizacao",
]


def _ler_tabela(diretorio: str, nome_arquivo: str) -> pd.DataFrame:
    caminho = os.path.join(diretorio, nome_arquivo)
    colunas = COLUNAS_POR_ARQUIVO[nome_arquivo]
    df = pd.read_csv(caminho, sep=";", encoding="latin-1", dtype=str, header=0, names=colunas)
    return df


def _titular_vigente(processo_pessoa: pd.DataFrame, pessoa: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por processo: titular vigente (IDTipoRelacao=titular, sem
    DTFimVigencia preenchido — mesmo critério confirmado manualmente para
    830.649/2020). Quando há mais de uma linha vigente (não deveria, mas
    dado real pode surpreender), fica com a de DTInicioVigencia mais
    recente, sem lançar exceção."""
    pp = processo_pessoa[processo_pessoa["IDTipoRelacao"].astype(str) == str(ID_TIPO_RELACAO_TITULAR)].copy()
    pp = pp[pp["DTFimVigencia"].isna() | (pp["DTFimVigencia"].astype(str).str.strip() == "")]
    pp = pp.sort_values("DTInicioVigencia").drop_duplicates("DSProcesso", keep="last")
    pp = pp.merge(pessoa, on="IDPessoa", how="left")
    return pp[["DSProcesso", "NMPessoa", "NRCPFCNPJ"]].rename(
        columns={"NMPessoa": "titular", "NRCPFCNPJ": "cnpj"})


def _substancia_vigente(processo_substancia: pd.DataFrame, substancia: pd.DataFrame) -> pd.DataFrame:
    ps = processo_substancia[
        processo_substancia["DTFimVigencia"].isna() | (processo_substancia["DTFimVigencia"].astype(str).str.strip() == "")
    ].copy()
    ps = ps.sort_values("DTInicioVigencia").drop_duplicates("DSProcesso", keep="last")
    ps = ps.merge(substancia, on="IDSubstancia", how="left")
    return ps[["DSProcesso", "NMSubstancia"]].rename(columns={"NMSubstancia": "substancia"})


def _municipios_por_processo(processo_municipio: pd.DataFrame, municipio: pd.DataFrame) -> pd.DataFrame:
    """Um processo pode ter mais de um município (ex.: 830.649/2020 tem
    dois) — agrega em uma string '; '-separada, mesma convenção que
    main.py já usa para o campo `events.municipio`, e mantém `uf_mg`
    (bool) para o filtro de presença territorial."""
    pm = processo_municipio.merge(municipio, on="IDMunicipio", how="left")
    presenca_mg = pm.groupby("DSProcesso")["SGUF"].apply(lambda s: (s.astype(str).str.upper() == "MG").any())
    nomes = pm.groupby("DSProcesso")["NMMunicipio"].apply(
        lambda s: "; ".join(sorted({str(v) for v in s if pd.notna(v)}))
    )
    out = pd.DataFrame({"municipio": nomes, "uf_mg": presenca_mg}).reset_index()
    return out


class TabelasAuxiliares:
    """Tabelas pequenas/médias do dump, lidas UMA vez. Só ProcessoEvento.txt (~1 GB) é grande o bastante
    para exigir leitura em blocos."""

    def __init__(self, diretorio_microdados: str):
        self.dic_evento = _ler_tabela(diretorio_microdados, "Evento.txt")
        self.processo = _ler_tabela(diretorio_microdados, "Processo.txt")
        proc_municipio = _ler_tabela(diretorio_microdados, "ProcessoMunicipio.txt")
        municipio = _ler_tabela(diretorio_microdados, "Municipio.txt")
        proc_substancia = _ler_tabela(diretorio_microdados, "ProcessoSubstancia.txt")
        substancia = _ler_tabela(diretorio_microdados, "Substancia.txt")
        proc_pessoa = _ler_tabela(diretorio_microdados, "ProcessoPessoa.txt")
        pessoa = _ler_tabela(diretorio_microdados, "Pessoa.txt")
        self.titular = _titular_vigente(proc_pessoa, pessoa)
        self.substancia_vigente = _substancia_vigente(proc_substancia, substancia)
        self.municipios = _municipios_por_processo(proc_municipio, municipio)

    def processos_em_mg(self) -> set:
        m = self.municipios
        return set(m.loc[m["uf_mg"] == True, "DSProcesso"])  # noqa: E712

    def ids_evento_fora_do_escopo(self) -> set:
        """IDEvento cujo nome (dicionário Evento.txt) cai numa família excluída (Carta §2). Calculado no
        dicionário (~3 mil linhas) em vez de em cada linha dos ~1 GB de eventos."""
        import classificacao_scm as clsf
        fam = [clsf.normalizar_termo(f) for f in FAMILIAS_FORA_DO_ESCOPO]
        out = set()
        for idev, nome in zip(self.dic_evento["IDEvento"], self.dic_evento["DSEvento"].fillna("")):
            t = clsf.normalizar_termo(nome)
            if any(f in t for f in fam):
                out.add(idev)
        return out


def _enriquecer(evento: pd.DataFrame, t: TabelasAuxiliares) -> pd.DataFrame:
    """Junta um pedaço (ou o todo) de ProcessoEvento às tabelas auxiliares. MESMO código para o caminho
    em memória e para o caminho em blocos — por isso os dois dão o mesmo resultado."""
    df = evento.merge(t.dic_evento, on="IDEvento", how="left")
    df = df.merge(t.processo[["DSProcesso", "QTAreaHA"]], on="DSProcesso", how="left")
    df = df.merge(t.titular, on="DSProcesso", how="left")
    df = df.merge(t.substancia_vigente, on="DSProcesso", how="left")
    df = df.merge(t.municipios, on="DSProcesso", how="left")

    df["evento_tipo"] = df["DSPublicacaoDOU"].where(
        df["DSPublicacaoDOU"].notna() & (df["DSPublicacaoDOU"].astype(str).str.strip() != ""),
        df["OBEvento"],
    )
    df["area_ha"] = df["QTAreaHA"].astype(str).str.replace(",", ".", regex=False)

    return pd.DataFrame({
        "processo": df["DSProcesso"],
        "id_tipo_evento": pd.to_numeric(df["IDEvento"], errors="coerce"),
        "descricao_tipo_evento": df["DSEvento"],
        "evento_tipo": df["evento_tipo"],
        "data_evento": df["DTEvento"],
        "titular": df["titular"],
        "cnpj": df["cnpj"],
        "substancia": df["substancia"],
        "municipio": df["municipio"],
        "uf_mg": df["uf_mg"].fillna(False),
        "area_ha": df["area_ha"],
    })


def carregar_microdados_scm(diretorio_microdados: str) -> pd.DataFrame:
    """Carrega TUDO em memória (uma linha por evento de processo). Serve para dumps pequenos/amostras e como
    referência de equivalência nos testes. Para o dump real (~1 GB de eventos) usar
    `carregar_recorte_m9a_em_blocos`.

    `diretorio_microdados` é o diretório já descompactado do zip oficial, com os `.txt` originais; o download
    e a descompactação ficam em baixar_scm.py."""
    t = TabelasAuxiliares(diretorio_microdados)
    evento = _ler_tabela(diretorio_microdados, "ProcessoEvento.txt")
    return _enriquecer(evento, t)


def conferir_cabecalhos(diretorio: str, avisos: Optional[list] = None) -> None:
    """Contrato do dump: número de colunas tem que bater (senão `names=` desalinharia tudo em silêncio).
    Nome diferente só gera aviso."""
    from pathlib import Path
    for arq, esperadas in COLUNAS_POR_ARQUIVO.items():
        p = Path(diretorio) / arq
        if not p.exists():
            raise FileNotFoundError(f"arquivo obrigatório ausente no dump: {arq}")
        cab = pd.read_csv(p, sep=";", encoding="latin-1", dtype=str, nrows=0).columns.tolist()
        if len(cab) != len(esperadas):
            raise ValueError(f"{arq}: {len(cab)} colunas no arquivo, {len(esperadas)} esperadas "
                             f"(cabeçalho recebido: {cab[:6]}...). O layout do dump oficial mudou.")
        norm = lambda c: str(c).replace("\ufeff", "").strip().lower()
        if [norm(c) for c in cab] != [norm(c) for c in esperadas] and avisos is not None:
            avisos.append(f"{arq}: nomes de coluna diferentes do esperado ({cab} vs {esperadas})")


def carregar_recorte_m9a_em_blocos(diretorio_microdados: str, tamanho_bloco: int = 500_000,
                                   max_linhas_evento: Optional[int] = None) -> tuple:
    """Lê ProcessoEvento.txt em blocos e aplica o recorte (presença em MG + exclusão de famílias fora do
    escopo) ANTES de juntar as demais tabelas — só o que está no recorte vira DataFrame enriquecido.
    Retorna (df_recorte, estatisticas). `max_linhas_evento` = modo amostra (primeiras N linhas de eventos),
    sem IA, para o primeiro teste pequeno. Resultado == aplicar_recorte_m9a(carregar_microdados_scm())."""
    avisos: list = []
    conferir_cabecalhos(diretorio_microdados, avisos)
    t = TabelasAuxiliares(diretorio_microdados)
    mg = t.processos_em_mg()
    fora = t.ids_evento_fora_do_escopo()
    colunas = COLUNAS_POR_ARQUIVO["ProcessoEvento.txt"]
    caminho = os.path.join(diretorio_microdados, "ProcessoEvento.txt")

    brutos = fora_mg = fora_familia = blocos = 0
    partes = []
    with pd.read_csv(caminho, sep=";", encoding="latin-1", dtype=str, header=0, names=colunas,
                     chunksize=tamanho_bloco) as leitor:
        for bloco in leitor:
            if max_linhas_evento is not None and brutos >= max_linhas_evento:
                break
            if max_linhas_evento is not None and brutos + len(bloco) > max_linhas_evento:
                bloco = bloco.iloc[: max_linhas_evento - brutos]
            blocos += 1
            brutos += len(bloco)
            em_mg = bloco["DSProcesso"].isin(mg)
            fora_mg += int((~em_mg).sum())
            bloco = bloco[em_mg]
            excl = bloco["IDEvento"].isin(fora)
            fora_familia += int(excl.sum())
            bloco = bloco[~excl]
            if len(bloco):
                partes.append(_enriquecer(bloco, t))

    if partes:
        df = pd.concat(partes, ignore_index=True)
    else:
        df = _enriquecer(pd.DataFrame(columns=colunas), t)
    est = {"brutos": brutos, "fora_de_mg": fora_mg, "fora_por_familia": fora_familia, "dentro_recorte": len(df),
           "blocos_lidos": blocos, "tamanho_bloco": tamanho_bloco, "amostra": max_linhas_evento is not None,
           "max_linhas_evento": max_linhas_evento, "avisos_cabecalho": avisos}
    return df, est


def filtrar_presenca_mg(df: pd.DataFrame) -> pd.DataFrame:
    """Carta §2: monitorar processos com presença territorial em MG, mesmo
    quando a sede da empresa está em outro estado — por isso filtra por
    UF do MUNICÍPIO DO PROCESSO (via ProcessoMunicipio/Municipio.SGUF),
    não por UF da empresa. `uf_mg` já vem calculado de
    carregar_microdados_scm()."""
    return df[df["uf_mg"] == True].copy()  # noqa: E712 (comparação explícita, coluna pode ter NaN/objeto)


def excluir_familias_fora_do_escopo(df: pd.DataFrame) -> pd.DataFrame:
    """Comparado contra `descricao_tipo_evento` (dicionário, estável) via
    normalização compartilhada — achado/correção de 28/09/2026: a versão
    anterior comparava contra `evento_tipo` (narrativa livre), o mesmo
    problema geral descrito em classificacao_scm.py."""
    import classificacao_scm as clsf
    normalizados = df["descricao_tipo_evento"].fillna("").map(clsf.normalizar_termo)
    mascara_fora = normalizados.apply(lambda t: any(clsf.normalizar_termo(f) in t for f in FAMILIAS_FORA_DO_ESCOPO))
    return df[~mascara_fora].copy()


def eh_evento_material(descricao_tipo_evento: str) -> bool:
    """Mantido por compatibilidade com chamadores existentes — ver
    signals.py para a classificação real usada na pontuação (esta função
    não é mais o caminho principal de decisão, `extrair_signais_m9a` já
    decide por sinal individual)."""
    import classificacao_scm as clsf
    from signals import EVENTOS_MUDANCA_MATERIAL, EVENTOS_AUTORIZACAO_EXTRACAO, EVENTOS_AVANCO_PESQUISA_APROVADO
    tipo = clsf.classificar(None, descricao_tipo_evento)
    return tipo.contem(*EVENTOS_MUDANCA_MATERIAL, *EVENTOS_AUTORIZACAO_EXTRACAO, *EVENTOS_AVANCO_PESQUISA_APROVADO)


def aplicar_recorte_m9a(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline completo do recorte (carta §2, calibração v0.2 §4):
    presença em MG -> exclusão de famílias fora do escopo."""
    df_mg = filtrar_presenca_mg(df)
    df_recorte = excluir_familias_fora_do_escopo(df_mg)
    return df_recorte
