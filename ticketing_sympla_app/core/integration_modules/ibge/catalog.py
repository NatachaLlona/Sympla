"""Pinned official Census 2022 products and variable definitions (IBGE dictionaries)."""
ROOT = 'https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/'
AGGREGATES = ROOT + 'Agregados_por_Setores_Censitarios/'
INCOME = ROOT + 'Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/'
DICTIONARIES = [
    AGGREGATES + 'dicionario_de_dados_agregados_por_setores_censitarios_20261113.xlsx',
    INCOME + 'dicionario_de_dados_renda_responsavel_20260508.xlsx',
]
AGE_BANDS = [
    ('0_4', '0 to 4 years', 0, 4, 'V01031'),
    ('5_9', '5 to 9 years', 5, 9, 'V01032'),
    ('10_14', '10 to 14 years', 10, 14, 'V01033'),
    ('15_19', '15 to 19 years', 15, 19, 'V01034'),
    ('20_24', '20 to 24 years', 20, 24, 'V01035'),
    ('25_29', '25 to 29 years', 25, 29, 'V01036'),
    ('30_39', '30 to 39 years', 30, 39, 'V01037'),
    ('40_49', '40 to 49 years', 40, 49, 'V01038'),
    ('50_59', '50 to 59 years', 50, 59, 'V01039'),
    ('60_69', '60 to 69 years', 60, 69, 'V01040'),
    ('70_plus', '70 years or older', 70, None, 'V01041'),
]
INDICATORS = {
    'population': ('Resident population', 'persons', 'Resident population, Census 2022'),
    'age_population': ('Population by published age band', 'persons', 'Population covered by the Census 2022 demography aggregate release; may differ from revised basic totals'),
    'responsible_income_mean': ('Mean monthly income of household responsible persons with income', 'BRL_nominal_2022', 'Responsible persons with income in occupied permanent private households'),
    'responsible_income_median': ('Median monthly income of household responsible persons with income', 'BRL_nominal_2022', 'Responsible persons with income in occupied permanent private households'),
    'household_per_capita_income_mean': ('Mean monthly household income per capita', 'BRL_nominal_2022', 'Census 2022 household per capita income universe; SIDRA 10295'),
    'household_per_capita_income_median': ('Median monthly household income per capita', 'BRL_nominal_2022', 'Census 2022 household per capita income universe; SIDRA 10295'),
}


def archive(level, topic):
    names = {'city': ('Municipio', 'municipios'), 'neighborhood': ('Bairro', 'bairros'), 'district': ('Distrito', 'distritos')}
    directory, plural = names[level]
    if topic == 'income':
        return INCOME + f'Agregados_por_{plural}_renda_responsavel_BR_20260508_csv.zip'
    suffix = 'basico_BR_20260520' if topic == 'base' else 'demografia_BR'
    return AGGREGATES + f'Agregados_por_{directory}_csv/Agregados_por_{plural}_{suffix}.zip'
