-- ROLLBACK (NÃO APLICADO) de 20261017_permissoes_perfil.sql. Remove só o que ela criou.
-- ATENÇÃO: aplique antes o rollback de 20261018_ia_assistida_leitura_admin (ele depende de tem_permissao).
drop function if exists public.minhas_permissoes();
drop function if exists public.tem_permissao(text);
drop table if exists public.perfil_permissoes;
