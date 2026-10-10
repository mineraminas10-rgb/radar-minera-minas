"""
Descoberta M8 contra um TRECHO REAL da página da SEMAD (salva em 10/10/2026): 3 cartões
(Caeté/04-10, Serra do Salitre sem data, um intermediário) + rodapé de paginação.
Prova: protocolo vem do nome da imagem, município/data vêm do título, cartão sem data
fica sem data (nunca inventada), a paginação é descoberta, e o extrator trata imagem por OCR.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "comum"))

import discovery  # noqa: E402
import extractor  # noqa: E402

HTML_REAL = r"""<html><body><dl><dd class=" card-page-item card-page-item-asset " data-qa-id="row" id="_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_entries_1" data-draggable="false" data-selectable="true" data-title="Comunicado de Acidente - Caeté/MG - 04/10/2026" data-actions=""> <div class="card-type-asset entry-display-style file-card form-check form-check-card form-check-top-left"> <div class="card"> <div class="aspect-ratio card-item-first"> <div class="custom-checkbox custom-control"> <label> <div class="custom-checkbox custom-control"><label><input class="custom-control-input custom-control-input" name="_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_rowIdsFileEntry" title="Selecionar" type="checkbox" value="10236593" data-modelclassname="FileEntry"><span class="custom-control-label"></span></label></div> <img alt="" class="aspect-ratio-item-center-middle aspect-ratio-item-fluid" src="./Comunicados de Acidentes Ambientais 2026 - SEMAD - SISEMA_files/Emergência ambiental 204_2026.png"> </label> </div> </div> <div class="card-body"> <div class="card-row"> <div class="autofit-col autofit-col-expand"> <div class="d-flex"> <a class="card-title text-truncate" href="https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026/-/document_library/vcfq/view_file/10236593?_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_redirect=https%3A%2F%2Fmeioambiente.mg.gov.br%2Fcomunicados-de-acidentes-ambientais-2026%3Fp_p_id%3Dcom_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq%26p_p_lifecycle%3D0%26p_p_state%3Dnormal%26p_p_mode%3Dview&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_fileEntryId=10236593" title="Comunicado de Acidente - Caeté/MG - 04/10/2026">Comunicado de Acidente - Caeté/MG - 04/10/2026</a> </div> <div class="card-subtitle text-truncate"> Modificado. </div> <div class="card-detail"> <div class="lfr-tooltip-scope"><span class="label label-success"><span class="label-item label-item-expand">Aprovado</span></span></div> </div> </div> </div> </div> </div> </div> </dd>
<dd class=" card-page-item card-page-item-asset " data-qa-id="row" id="_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_entries_4" data-draggable="false" data-selectable="true" data-title="Comunicado de Acidente - Serra do Salitre/MG" data-actions=""> <div class="card-type-asset entry-display-style file-card form-check form-check-card form-check-top-left"> <div class="card"> <div class="aspect-ratio card-item-first"> <div class="custom-checkbox custom-control"> <label> <div class="custom-checkbox custom-control"><label><input class="custom-control-input custom-control-input" name="_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_rowIdsFileEntry" title="Selecionar" type="checkbox" value="10234438" data-modelclassname="FileEntry"><span class="custom-control-label"></span></label></div> <img alt="" class="aspect-ratio-item-center-middle aspect-ratio-item-fluid" src="./Comunicados de Acidentes Ambientais 2026 - SEMAD - SISEMA_files/Emergência ambiental 201_2026.png"> </label> </div> </div> <div class="card-body"> <div class="card-row"> <div class="autofit-col autofit-col-expand"> <div class="d-flex"> <a class="card-title text-truncate" href="https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026/-/document_library/vcfq/view_file/10234438?_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_redirect=https%3A%2F%2Fmeioambiente.mg.gov.br%2Fcomunicados-de-acidentes-ambientais-2026%3Fp_p_id%3Dcom_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq%26p_p_lifecycle%3D0%26p_p_state%3Dnormal%26p_p_mode%3Dview&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_fileEntryId=10234438" title="Comunicado de Acidente - Serra do Salitre/MG">Comunicado de Acidente - Serra do Salitre/MG</a> </div> <div class="card-subtitle text-truncate"> Modificado. </div> <div class="card-detail"> <div class="lfr-tooltip-scope"><span class="label label-success"><span class="label-item label-item-expand">Aprovado</span></span></div> </div> </div> </div> </div> </div> </div> </dd>
<dd class=" card-page-item card-page-item-asset " data-qa-id="row" id="_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_entries_11" data-draggable="false" data-selectable="true" data-title="Comunicado de Acidente - Belo Horizonte/MG - 18/09/2026" data-actions=""> <div class="card-type-asset entry-display-style file-card form-check form-check-card form-check-top-left"> <div class="card"> <div class="aspect-ratio card-item-first"> <div class="custom-checkbox custom-control"> <label> <div class="custom-checkbox custom-control"><label><input class="custom-control-input custom-control-input" name="_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_rowIdsFileEntry" title="Selecionar" type="checkbox" value="10217455" data-modelclassname="FileEntry"><span class="custom-control-label"></span></label></div> <img alt="" class="aspect-ratio-item-center-middle aspect-ratio-item-fluid" src="./Comunicados de Acidentes Ambientais 2026 - SEMAD - SISEMA_files/Emergência ambiental 194_2026.png"> </label> </div> </div> <div class="card-body"> <div class="card-row"> <div class="autofit-col autofit-col-expand"> <div class="d-flex"> <a class="card-title text-truncate" href="https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026/-/document_library/vcfq/view_file/10217455?_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_redirect=https%3A%2F%2Fmeioambiente.mg.gov.br%2Fcomunicados-de-acidentes-ambientais-2026%3Fp_p_id%3Dcom_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq%26p_p_lifecycle%3D0%26p_p_state%3Dnormal%26p_p_mode%3Dview&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_fileEntryId=10217455" title="Comunicado de Acidente - Belo Horizonte/MG - 18/09/2026">Comunicado de Acidente - Belo Horizonte/MG - 18/09/2026</a> </div> <div class="card-subtitle text-truncate"> Modificado. </div> <div class="card-detail"> <div class="lfr-tooltip-scope"><span class="label label-success"><span class="label-item label-item-expand">Aprovado</span></span></div> </div> </div> </div> </div> </div> </div> </dd></dl><p class="pagination-results">Exibindo 1 - 20 de 190 resultados.</p><nav><ul class="pagination"><li class="active page-item"><a class="page-link" href="https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026/-/document_library/vcfq/view/9806481?_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_folderId=9806481&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_navigation=home&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_orderByCol=modifiedDate&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_orderByType=desc&amp;p_r_p_resetCur=false&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_deltaEntry=20&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_curEntry=1">1</a></li><li><a class="page-link" href="https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026/-/document_library/vcfq/view/9806481?_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_folderId=9806481&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_navigation=home&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_orderByCol=modifiedDate&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_orderByType=desc&amp;p_r_p_resetCur=false&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_deltaEntry=20&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_curEntry=2" onclick="">2</a></li><li><a class="page-link" href="https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026/-/document_library/vcfq/view/9806481?_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_folderId=9806481&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_navigation=home&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_orderByCol=modifiedDate&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_orderByType=desc&amp;p_r_p_resetCur=false&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_deltaEntry=20&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_curEntry=3" onclick="">3</a></li><li><ul><li><a class="dropdown-item" href="https://meioambiente.mg.gov.br/comunicados-de-acidentes-ambientais-2026/-/document_library/vcfq/view/9806481?_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_folderId=9806481&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_navigation=home&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_orderByCol=modifiedDate&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_orderByType=desc&amp;p_r_p_resetCur=false&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_deltaEntry=20&amp;_com_liferay_document_library_web_portlet_DLPortlet_INSTANCE_vcfq_curEntry=4" id="zqca_4" onclick="" role="menuitem">4</a></li></ul></li></ul></nav></body></html>"""


class TestDescobertaContraHtmlReal(unittest.TestCase):

    def setUp(self):
        self.itens = discovery.parse_inventario(HTML_REAL, base_url=discovery.URL_PAGINA_ANUAL)

    def test_reconhece_os_tres_cartoes(self):
        self.assertEqual(len(self.itens), 3)

    def test_protocolo_vem_do_nome_da_imagem(self):
        primeiro = self.itens[0]
        self.assertEqual((primeiro.protocolo, primeiro.ano), ("204", 2026))
        self.assertEqual(primeiro.protocolo_origem, "nome_da_imagem")

    def test_municipio_e_data_vem_do_titulo(self):
        primeiro = self.itens[0]
        self.assertEqual(primeiro.municipio, "Caeté")
        self.assertEqual(primeiro.data_publicada, "04/10/2026")
        self.assertEqual(primeiro.id_arquivo, "10236593")
        self.assertTrue(primeiro.url_detalhe.startswith("https://meioambiente.mg.gov.br/"))
        self.assertIn("view_file/10236593", primeiro.url_detalhe)

    def test_cartao_sem_data_no_titulo_fica_sem_data(self):
        sem_data = self.itens[1]
        self.assertEqual(sem_data.municipio, "Serra do Salitre")
        self.assertIsNone(sem_data.data_publicada)

    def test_hash_estavel_e_distinto_por_item(self):
        outros = discovery.parse_inventario(HTML_REAL)
        self.assertEqual([i.hash_linha for i in self.itens], [i.hash_linha for i in outros])
        self.assertEqual(len({i.hash_linha for i in self.itens}), 3)

    def test_total_e_paginas(self):
        self.assertEqual(discovery.total_informado(HTML_REAL), 190)
        urls = discovery.urls_outras_paginas(HTML_REAL)
        self.assertEqual(len(urls), 3)   # páginas 2, 3 e 4 (a 1 não se repete)
        self.assertTrue(all("curEntry=" in u and u.startswith("https://") for u in urls))
        self.assertNotIn("curEntry=1", urls[0])

    def test_pagina_sem_cartoes_devolve_vazio(self):
        self.assertEqual(discovery.parse_inventario("<html><body><p>Manutenção</p></body></html>"), [])

    def test_cartao_sem_nome_de_imagem_usa_id_do_arquivo(self):
        html = HTML_REAL.replace("Emergência ambiental 204_2026.png", "miniatura.png")
        item = discovery.parse_inventario(html)[0]
        self.assertEqual(item.protocolo, "arq10236593")
        self.assertEqual(item.protocolo_origem, "id_do_arquivo")

    def test_titulo_fora_do_padrao_nao_inventa_municipio(self):
        self.assertEqual(discovery.interpretar_titulo("Aviso geral")["municipio"], None)
        t = discovery.interpretar_titulo("Comunicado de Acidente - São João Del Rei/MG - 11/09/2026")
        self.assertEqual((t["municipio"], t["uf"], t["data"]), ("São João Del Rei", "MG", "11/09/2026"))

    def test_comparacao_com_inventario_anterior(self):
        r = discovery.comparar_com_inventario_anterior(self.itens, {("204", 2026): self.itens[0].hash_linha})
        self.assertEqual((len(r["novos"]), len(r["identicos"]), len(r["alterados"])), (2, 1, 0))


class _Resp:
    def __init__(self, corpo, ctype, url="https://meioambiente.mg.gov.br/x"):
        self.corpo, self.content_type, self.url_final = corpo, ctype, url


class _Acessador:
    def __init__(self, respostas):
        self.respostas, self.pedidos = respostas, []

    def get(self, url, metodo_acesso=None):
        self.pedidos.append(url)
        return self.respostas[url]


class TestExtratorComImagem(unittest.TestCase):

    def test_documento_em_imagem_vai_para_ocr(self):
        ocr = ("COMUNICADO DE ACIDENTE AMBIENTAL\nMUNICIPIO: Caeté/MG\n" * 3, "boa", 1)
        with mock.patch.object(extractor, "_ocr_de_imagens", return_value=ocr):
            from PIL import Image
            import io
            buf = io.BytesIO(); Image.new("RGB", (40, 40), "white").save(buf, "PNG")
            r = extractor.extrair("https://meioambiente.mg.gov.br/documents/1/2/a.png",
                                  acessador=_Acessador({"https://meioambiente.mg.gov.br/documents/1/2/a.png":
                                                        _Resp(buf.getvalue(), "image/png")}))
        self.assertEqual(r.status_processamento, "processado")
        self.assertEqual(r.metodo_extracao, "ocr")
        self.assertIn("Caeté", r.texto)

    def test_pagina_de_visualizacao_abre_a_imagem_e_ignora_texto_de_menu(self):
        url_pag = "https://meioambiente.mg.gov.br/comunicados/-/document_library/vcfq/view_file/10236593?x=1"
        url_img = "https://meioambiente.mg.gov.br/documents/9806481/10236593/Emergencia+204_2026.png/abc"
        html = ("<html><body><nav>Menu Menu Menu</nav><main>" + "texto de menu do site " * 30 +
                f'<img src="{url_img}"></main></body></html>').encode()
        ac = _Acessador({url_pag: _Resp(html, "text/html", url_pag), url_img: _Resp(b"png", "image/png", url_img)})
        ocr = ("Nº Protocolo: 204/2026 Município: Caeté/MG vazamento de óleo diesel", "boa", 1)
        with mock.patch.object(extractor, "_ocr_de_imagens", return_value=ocr), \
             mock.patch("PIL.Image.open") as abre:
            abre.return_value.convert.return_value = object()
            r = extractor.extrair(url_pag, acessador=ac)
        self.assertEqual(r.status_processamento, "processado")
        self.assertNotIn("menu do site", r.texto)
        self.assertIn("204/2026", r.texto)
        self.assertEqual(ac.pedidos, [url_pag, url_img])

    def test_pagina_de_visualizacao_sem_documento_e_falha_explicita(self):
        url_pag = "https://meioambiente.mg.gov.br/comunicados/-/document_library/vcfq/view_file/1?x=1"
        html = ("<html><body>" + "texto de menu do site " * 40 + "</body></html>").encode()
        r = extractor.extrair(url_pag, acessador=_Acessador({url_pag: _Resp(html, "text/html", url_pag)}))
        self.assertEqual(r.status_processamento, "falha_extracao")
        self.assertIn("documentos encontrados na página: 0", r.motivo_falha)

    def test_candidatos_excluem_recursos_do_tema_e_hosts_externos(self):
        html = ('<a href="/o/tema/x.png">t</a><img src="/o/tema/logo.png"><a href="https://externo.com/a.pdf">e</a>'
                '<a href="/documents/1/2/a.pdf">ok</a><img src="/documents/1/2/b.png">')
        c = extractor.candidatos_documento(html, "https://meioambiente.mg.gov.br/p")
        self.assertEqual(c, ["https://meioambiente.mg.gov.br/documents/1/2/a.pdf",
                             "https://meioambiente.mg.gov.br/documents/1/2/b.png"])


if __name__ == "__main__":
    unittest.main()
