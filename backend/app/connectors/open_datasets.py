"""Open watchlists downloaded as bulk files (no API key).

EU, UK and Swiss sanctions, World Bank debarments and Interpol red notices,
from the normalised bulk exports published by OpenSanctions
(https://www.opensanctions.org/datasets/: `targets.simple.csv`). The same
format for every list keeps parsing reliable. The files are downloaded once
per server instance (refreshed every 12 h) and indexed by name.

Licence: OpenSanctions data is CC BY-NC 4.0: free for non-commercial use
(this portfolio project); commercial use requires a licence.
"""

from __future__ import annotations

import contextlib
import csv
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.connectors.base import USER_AGENT, BaseConnector, ConnectorError
from app.connectors.official_sanctions import ListedEntry, _Index
from app.matching.matcher import match_entities
from app.models import Entity, EntityType, ListType, ScreeningHit

URL = "https://data.opensanctions.org/datasets/latest/{dataset}/targets.simple.csv"
ENTITY_URL = "https://www.opensanctions.org/entities/{id}/"
REFRESH_SECONDS = 12 * 3600
MIN_SCORE = 60

DATASETS = {
    "eu_fsf": ("EU Financial Sanctions Files (consolidated list)", ListType.SANCTION),
    "gb_fcdo_sanctions": ("UK Sanctions List (FCDO)", ListType.SANCTION),
    "gb_hmt_sanctions": ("UK financial sanctions (HM Treasury / OFSI)", ListType.SANCTION),
    "ch_seco_sanctions": ("Swiss sanctions (SECO)", ListType.SANCTION),
    "ca_dfatd_sema_sanctions": ("Canada autonomous sanctions (SEMA)", ListType.SANCTION),
    "au_dfat_sanctions": ("Australia consolidated sanctions (DFAT)", ListType.SANCTION),
    "jp_mof_sanctions": ("Japan economic sanctions (Ministry of Finance)", ListType.SANCTION),
    "worldbank_debarred": ("World Bank debarred firms and individuals", ListType.ADVERSE),
    "interpol_red_notices": ("Interpol red notices (public)", ListType.ADVERSE),
    # Investigative lists (journalists / NGOs / governments documenting networks)
    "ru_acf_bribetakers": (
        "ACF (Navalny Anti-Corruption Foundation): War Enablers investigation",
        ListType.ADVERSE,
    ),
    "ua_war_sanctions": ("Ukraine War & Sanctions (NAZK): enablers of the war", ListType.ADVERSE),
    "wd_oligarchs": ("Russian oligarchs and billionaires (Wikidata)", ListType.ADVERSE),
    # Professional bans and regulator warnings
    "gb_coh_disqualified": ("UK disqualified directors (Companies House)", ListType.ADVERSE),
    "ch_finma_warnings": ("Swiss FINMA warning list (unauthorised firms)", ListType.ADVERSE),
    # More sanctions regimes (Belgium, New Zealand, Baltic Magnitsky, Navalny list)
    "be_fod_sanctions": ("Belgian financial sanctions (FPS Finance)", ListType.SANCTION),
    "nz_russia_sanctions": ("New Zealand Russia sanctions", ListType.SANCTION),
    "lv_magnitsky_list": ("Latvia Magnitsky law sanctions", ListType.SANCTION),
    "ru_navalny35": ("Navalny 35: individuals proposed for sanctions", ListType.ADVERSE),
    # Development-bank and EU debarments (fraud, corruption in funded projects)
    "afdb_sanctions": ("African Development Bank debarments", ListType.ADVERSE),
    "adb_sanctions": ("Asian Development Bank sanctions", ListType.ADVERSE),
    "iadb_sanctions": ("Inter-American Development Bank sanctions", ListType.ADVERSE),
    "ebrd_ineligible": ("EBRD ineligible entities", ListType.ADVERSE),
    "eu_edes": ("EU Early Detection and Exclusion System (EDES)", ListType.ADVERSE),
    # Financial regulators: enforcement and warnings (CH, LU, FR, EU, US)
    "lu_administrative_sanctions": ("Luxembourg CSSF administrative sanctions", ListType.ADVERSE),
    "ch_finma_rulings": ("Swiss FINMA final rulings", ListType.ADVERSE),
    "fr_amf_regulatory_sanctions": ("France AMF regulatory sanctions", ListType.ADVERSE),
    "fr_illegal_financial_services": (
        "France AMF blacklist (illegal financial services)",
        ListType.ADVERSE,
    ),
    "eu_esma_sanctions": ("EU ESMA sanctions", ListType.ADVERSE),
    "us_sec_pause": ("US SEC public alert: unregistered soliciting entities", ListType.ADVERSE),
    "no_nbim_exclusions": (
        "Norway sovereign fund (NBIM) exclusions (ethics, corruption)",
        ListType.ADVERSE,
    ),
    # Public officials (French HATVP declarations of interests and assets)
    "fr_hatvp_declarations": (
        "France HATVP: declarations of interests of public officials",
        ListType.PEP,
    ),
    # Law enforcement
    "eu_europol_wanted": ("Europol: Europe's most wanted", ListType.ADVERSE),
    "gb_nca_most_wanted": ("UK National Crime Agency most wanted", ListType.ADVERSE),
    "gb_nca_press_releases": (
        "UK National Crime Agency press releases (convictions)",
        ListType.ADVERSE,
    ),
    "us_fbi_most_wanted": ("US FBI most wanted", ListType.ADVERSE),
    "de_bka_wanted": ("Germany BKA wanted fugitives", ListType.ADVERSE),
    # National asset freezes and sanctions regimes not in the EU / UN lists
    "fr_tresor_gels_avoir": ("France national asset freezes (DG Trésor)", ListType.SANCTION),
    "mc_fund_freezes": ("Monaco national fund freezes", ListType.SANCTION),
    "ch_fiaa_freezes": ("Swiss freezes of assets of foreign PEPs (FIAA)", ListType.SANCTION),
    "eu_travel_bans": ("EU consolidated travel bans", ListType.SANCTION),
    "ee_international_sanctions": ("Estonia international sanctions", ListType.SANCTION),
    "lv_fiu_sanctions": ("Latvia FIU sanctions and asset freezes", ListType.SANCTION),
    "lt_magnitsky_amendments": ("Lithuania Magnitsky sanctions", ListType.SANCTION),
    "pl_mswia_sanctions": (
        "Poland national sanctions (Ministry of the Interior)",
        ListType.SANCTION,
    ),
    "cz_national_sanctions": ("Czech Republic national sanctions", ListType.SANCTION),
    "ca_facfoa": ("Canada freezes of assets of corrupt foreign officials", ListType.SANCTION),
    "us_klepto_hr_visa": ("US anti-kleptocracy visa restrictions", ListType.SANCTION),
    "us_bis_denied": ("US BIS denied persons (export bans)", ListType.SANCTION),
    "us_fincen_special_measures": ("US FinCEN 311 / 9714 special measures", ListType.SANCTION),
    "tr_fcib": ("Türkiye asset freezes (MASAK)", ListType.SANCTION),
    "za_fic_sanctions": ("South Africa targeted financial sanctions", ListType.SANCTION),
    "jp_meti_ru": ("Japan METI export sanctions: Russia", ListType.SANCTION),
    # Financial regulators: enforcement actions, bans and consumer alerts
    "us_fincen_enforcement": ("US FinCEN enforcement actions (AML)", ListType.ADVERSE),
    "us_ofac_enforcement_actions": (
        "US OFAC enforcement actions (sanctions breaches)",
        ListType.ADVERSE,
    ),
    "us_cftc_enforcement_actions": ("US CFTC enforcement actions", ListType.ADVERSE),
    "us_nfa_enforcement_actions": ("US NFA enforcement actions", ListType.ADVERSE),
    "us_finra_barred": ("US FINRA barred individuals", ListType.ADVERSE),
    "us_ddtc_debarred": ("US State Department arms-export debarments", ListType.ADVERSE),
    "ae_dfsa_prohibited": ("Dubai DFSA prohibited / restricted individuals", ListType.ADVERSE),
    "my_consumer_alert_list": ("Malaysia financial consumer alert list", ListType.ADVERSE),
    "lt_illegal_websites": ("Lithuania illegal financial services", ListType.ADVERSE),
    # Law enforcement
    "hk_icac_wanted": ("Hong Kong ICAC wanted (corruption)", ListType.ADVERSE),
    "us_dea_fugitives": ("US DEA fugitives", ListType.ADVERSE),
    # Politically exposed persons: national parliaments and governments (public lists)
    "us_cia_world_leaders": ("PEP: World leaders and cabinet members (CIA)", ListType.PEP),
    "un_ga_protocol": (
        "PEP: Heads of State, Government and Foreign Ministers (UN protocol)",
        ListType.PEP,
    ),
    "eu_meps": ("PEP: European Parliament members", ListType.PEP),
    "eu_cor_members": ("PEP: EU Committee of the Regions members", ListType.PEP),
    "fr_assemblee": ("PEP, France, National Assembly members", ListType.PEP),
    "fr_senat": ("PEP, France, Senators", ListType.PEP),
    "mc_conseil_national": ("PEP, Monaco, National Council members", ListType.PEP),
    "ch_parlament": ("PEP, Switzerland, Federal Assembly members", ListType.PEP),
    "li_landtag": ("PEP, Liechtenstein, Landtag members", ListType.PEP),
    "lu_chamber": ("PEP, Luxembourg, Chamber of Deputies members", ListType.PEP),
    "lu_bourgmestres": ("PEP, Luxembourg, mayors and aldermen", ListType.PEP),
    "be_chamber": ("PEP, Belgium, Chamber of Representatives members", ListType.PEP),
    "be_senate": ("PEP, Belgium, Senators", ListType.PEP),
    "nl_house_of_representatives": (
        "PEP, Netherlands, House of Representatives members",
        ListType.PEP,
    ),
    "nl_senate": ("PEP, Netherlands, Senators", ListType.PEP),
    "de_bundestag": ("PEP, Germany, Bundestag members", ListType.PEP),
    "de_bundesrat": ("PEP, Germany, Bundesrat members", ListType.PEP),
    "at_parlament": ("PEP, Austria, Parliament members", ListType.PEP),
    "it_deputies": ("PEP, Italy, Chamber of Deputies members", ListType.PEP),
    "it_senate": ("PEP, Italy, Senators", ListType.PEP),
    "es_parliament": ("PEP, Spain, Parliament members", ListType.PEP),
    "pt_parliament": ("PEP, Portugal, Assembly members", ListType.PEP),
    "gb_commons": ("PEP, UK, House of Commons members", ListType.PEP),
    "gb_lords": ("PEP, UK, House of Lords members", ListType.PEP),
    "ie_parliament": ("PEP, Ireland, Parliament members", ListType.PEP),
    "mt_parlament": ("PEP, Malta, Parliament members", ListType.PEP),
    "cy_parliament": ("PEP, Cyprus, House of Representatives members", ListType.PEP),
    "gr_parliament": ("PEP, Greece, Parliament members", ListType.PEP),
    "dk_pep": ("PEP: Denmark, Faroe Islands and Greenland PEPs", ListType.PEP),
    "se_riksdag": ("PEP, Sweden, Riksdag members", ListType.PEP),
    "no_storting": ("PEP, Norway, Storting members", ListType.PEP),
    "fi_eduskunta": ("PEP, Finland, Parliament members", ListType.PEP),
    "ee_riigikogu": ("PEP, Estonia, Riigikogu members", ListType.PEP),
    "lv_saeima": ("PEP, Latvia, Saeima members", ListType.PEP),
    "lt_seimas": ("PEP, Lithuania, Seimas members", ListType.PEP),
    "pl_sejm": ("PEP, Poland, Sejm members", ListType.PEP),
    "pl_senate": ("PEP, Poland, Senators", ListType.PEP),
    "cz_pep_declarations": ("PEP, Czech Republic, declared PEPs", ListType.PEP),
    "sk_nrsr_poslanci": ("PEP, Slovakia, National Council members", ListType.PEP),
    "hu_national_assembly": ("PEP, Hungary, National Assembly members", ListType.PEP),
    "si_dz_rs": ("PEP, Slovenia, National Assembly members", ListType.PEP),
    "hr_sabor": ("PEP, Croatia, Parliament members", ListType.PEP),
    "ro_cdep_deputies": ("PEP, Romania, Chamber of Deputies members", ListType.PEP),
    "ro_senate": ("PEP, Romania, Senators", ListType.PEP),
    "bg_parliament": ("PEP, Bulgaria, National Assembly members", ListType.PEP),
    "rs_national_assembly": ("PEP, Serbia, National Assembly members", ListType.PEP),
    "ua_rada": ("PEP, Ukraine, Verkhovna Rada members", ListType.PEP),
    "ru_duma_deputies": ("PEP, Russia, State Duma deputies", ListType.PEP),
    "ru_federation_council": ("PEP, Russia, Federation Council members", ListType.PEP),
    "ge_parliament": ("PEP, Georgia, Parliament members", ListType.PEP),
    "am_national_assembly": ("PEP, Armenia, National Assembly members", ListType.PEP),
    "az_parliament": ("PEP, Azerbaijan, National Assembly members", ListType.PEP),
    "kz_mazhilis": ("PEP, Kazakhstan, Mazhilis members", ListType.PEP),
    "tr_parliament": ("PEP, Türkiye, Grand National Assembly members", ListType.PEP),
    "il_knesset_members": ("PEP, Israel, Knesset members", ListType.PEP),
    "us_congress": ("PEP, US, Congress members", ListType.PEP),
    "us_state_dept": ("PEP, US, State Department senior officials", ListType.PEP),
    "ca_commons": ("PEP, Canada, House of Commons members", ListType.PEP),
}
# Second batch (OpenDatasetsExtendedConnector, loaded in the background)
DATASETS.update(
    {
        "ua_nsdc_sanctions": ("Ukraine NSDC state register of sanctions", ListType.SANCTION),
        "ua_sfms_blacklist": ("Ukraine SFMS (financial monitoring) blacklist", ListType.SANCTION),
        "us_ofac_cons": ("US OFAC consolidated non-SDN lists", ListType.SANCTION),
        "us_state_terrorist_orgs": (
            "US State Department foreign terrorist organisations",
            ListType.SANCTION,
        ),
        "us_state_terrorist_exclusion": (
            "US State Department terrorist exclusion list",
            ListType.SANCTION,
        ),
        "us_cuba_sanctions": ("US State Department Cuba restricted list", ListType.SANCTION),
        "us_dhs_uflpa": ("US UFLPA entity list (forced labour, Xinjiang)", ListType.SANCTION),
        "us_bis_mieu": ("US BIS military-intelligence end users", ListType.SANCTION),
        "us_cbp_forced_labor": (
            "US CBP withhold release orders (forced labour)",
            ListType.SANCTION,
        ),
        "us_nk_jointventures": ("US advisory on North Korean joint ventures", ListType.SANCTION),
        "us_dod_chinese_milcorps": ("US DoD Chinese military companies", ListType.SANCTION),
        "us_fcc_covered_list": ("US FCC covered list (national security)", ListType.SANCTION),
        "gb_proscribed_orgs": ("UK proscribed terrorist organisations", ListType.SANCTION),
        "ca_listed_terrorists": ("Canada listed terrorist entities", ListType.SANCTION),
        "au_listed_terrorist_orgs": ("Australia listed terrorist organisations", ListType.SANCTION),
        "nz_designated_terrorists": (
            "New Zealand designated terrorist entities",
            ListType.SANCTION,
        ),
        "nl_terrorism_list": ("Netherlands national terrorism sanctions list", ListType.SANCTION),
        "cz_terrorists": ("Czech national anti-terrorism designations", ListType.SANCTION),
        "at_nbter_sanctions": ("Austria OeNB terrorism financing restrictions", ListType.SANCTION),
        "lt_fiu_freezes": ("Lithuania FIU international sanctions", ListType.SANCTION),
        "pl_finanse_sanctions": ("Poland Ministry of Finance AML/CFT sanctions", ListType.SANCTION),
        "ro_onpcsb_sanctions": ("Romania list of suspected terrorists", ListType.SANCTION),
        "bg_mft_national": ("Bulgaria national terrorism financing list", ListType.SANCTION),
        "rs_apml_domestic": ("Serbia domestic designated persons", ListType.SANCTION),
        "md_terror_sanctions": ("Moldova terrorism and proliferation sanctions", ListType.SANCTION),
        "ge_ot_list": ("Georgia Otkhozoria–Tatunashvili list", ListType.SANCTION),
        "az_fiu_sanctions": ("Azerbaijan FIU domestic list", ListType.SANCTION),
        "kg_fiu_national": ("Kyrgyzstan FIU national list", ListType.SANCTION),
        "il_mod_terrorists": (
            "Israel terrorist organisations and unauthorised associations",
            ListType.SANCTION,
        ),
        "il_wmd_sanctions": ("Israel WMD financing designations", ListType.SANCTION),
        "ae_local_terrorists": ("United Arab Emirates local terrorist list", ListType.SANCTION),
        "qa_nctc_sanctions": ("Qatar national sanctions list", ListType.SANCTION),
        "sa_pcct_terrorism_list": ("Saudi Arabia national terrorism list", ListType.SANCTION),
        "jo_sanctions": ("Jordan national sanctions list", ListType.SANCTION),
        "iq_aml_list": ("Iraq terrorist fund freezing lists", ListType.SANCTION),
        "eg_terrorists": ("Egypt domestic terrorist list", ListType.SANCTION),
        "tn_cnlct": ("Tunisia national counter-terrorism list", ListType.SANCTION),
        "ke_frc_sanctions": ("Kenya FRC domestic terrorism list", ListType.SANCTION),
        "ng_nigsac_sanctions": ("Nigeria sanctions list", ListType.SANCTION),
        "in_mha_banned": ("India banned organisations", ListType.SANCTION),
        "pk_proscribed_persons": ("Pakistan NACTA proscribed persons", ListType.ADVERSE),
        "np_mha_sanctions": ("Nepal prohibited persons and groups", ListType.SANCTION),
        "id_dttot": ("Indonesia suspected terrorists list (DTTOT)", ListType.SANCTION),
        "my_moha_sanctions": ("Malaysia MOHA sanctions list", ListType.SANCTION),
        "sg_terrorists": ("Singapore targeted financial sanctions", ListType.SANCTION),
        "th_designated_person": ("Thailand designated persons", ListType.SANCTION),
        "ph_amlc_sanctions": ("Philippines AMLC sanctions", ListType.SANCTION),
        "vn_terrorist_orgs": ("Vietnam terrorist organisations and individuals", ListType.SANCTION),
        "ps_local_freezing": ("Palestine Monetary Authority freezing list", ListType.SANCTION),
        "ar_repet": ("Argentina RePET terrorism sanctions", ListType.SANCTION),
        "de_bfv_extremism": ("Germany banned extremist organisations", ListType.ADVERSE),
        "ie_unlawful_organizations": ("Ireland unlawful organisations", ListType.SANCTION),
        "jp_meti_eul": ("Japan METI end user list (export controls)", ListType.SANCTION),
        "us_fed_enforcements": ("US Federal Reserve enforcement actions", ListType.ADVERSE),
        "us_occ_enfact": ("US OCC enforcement actions (banks)", ListType.ADVERSE),
        "us_bis_export": ("US BIS export violations", ListType.ADVERSE),
        "us_bis_antiboycott": ("US BIS antiboycott violations", ListType.ADVERSE),
        "us_ddtc_enforcements": ("US State Department arms-export penalties", ListType.ADVERSE),
        "us_sec_harmed_investors": ("US SEC actions for harmed investors", ListType.ADVERSE),
        "us_special_leg": ("US special legislative exclusions", ListType.ADVERSE),
        "gg_disqualified_directors": (
            "Guernsey FSC prohibitions and disqualified directors",
            ListType.ADVERSE,
        ),
        "im_disqualified_directors": ("Isle of Man disqualified directors", ListType.ADVERSE),
        "tr_cmb_banned": ("Türkiye Capital Markets Board banned list", ListType.ADVERSE),
        "in_nse_debarred": ("India National Stock Exchange debarred entities", ListType.ADVERSE),
        "my_aob_sanctions": (
            "Malaysia Securities Commission audit oversight enforcement",
            ListType.ADVERSE,
        ),
        "my_investor_alert_list": (
            "Malaysia Securities Commission investor alerts",
            ListType.ADVERSE,
        ),
        "ph_sec_advisories": ("Philippines SEC advisories", ListType.ADVERSE),
        "ph_gppb_debarred": ("Philippines procurement blacklist", ListType.ADVERSE),
        "br_ceis": (
            "Brazil register of disreputable and suspended companies (CEIS)",
            ListType.ADVERSE,
        ),
        "br_tcu_debarred": ("Brazil TCU debarred bidders", ListType.ADVERSE),
        "br_bcb_disqualified_persons": (
            "Brazil Central Bank disqualified persons",
            ListType.ADVERSE,
        ),
        "md_interdictie": ("Moldova ban list of economic operators", ListType.ADVERSE),
        "si_conflicts": (
            "Slovenia business restrictions (conflicts of interest)",
            ListType.ADVERSE,
        ),
        "lt_illegal_gambling": ("Lithuania illegal gambling operators", ListType.ADVERSE),
        "li_entsg": ("Liechtenstein posted workers act sanctions", ListType.ADVERSE),
        "br_slavery": ("Brazil slave-labour employers list", ListType.ADVERSE),
        "ru_dossier_center_poi": (
            "Dossier Center: Russian persons of interest (investigation)",
            ListType.ADVERSE,
        ),
        "ru_kremlin_persons": ("Kremlin catalogue of persons (kremlin.ru)", ListType.ADVERSE),
        "ru_billionaires_2021": ("Forbes Russian billionaires 2021", ListType.ADVERSE),
        "md_rise_profiles": (
            "RISE Moldova: persons of interest (investigation)",
            ListType.ADVERSE,
        ),
        "thesentry_atlas": ("The Sentry: kleptocracy atlas (investigation)", ListType.ADVERSE),
        "ir_uani_business_registry": ("UANI: companies doing business in Iran", ListType.ADVERSE),
        "shu_uyghur_companies": (
            "Companies operating in the Uyghur region (Sheffield Hallam)",
            ListType.ADVERSE,
        ),
        "c4ads_xinjiang": ("C4ADS: Xinjiang supply chains (investigation)", ListType.ADVERSE),
        "ps_ohchr_settlement": (
            "UN OHCHR companies linked to West Bank settlements",
            ListType.ADVERSE,
        ),
        "tr_wanted": ("Türkiye terrorist wanted list", ListType.ADVERSE),
        "es_cnp_wanted": ("Spain National Police most wanted", ListType.ADVERSE),
        "nl_most_wanted": ("Netherlands police most wanted", ListType.ADVERSE),
        "us_ice_wanted": ("US ICE most wanted", ListType.ADVERSE),
        "us_ss_wanted": ("US Secret Service most wanted", ListType.ADVERSE),
        "za_wanted": ("South Africa wanted persons", ListType.ADVERSE),
        "ar_parliament": ("PEP, Argentina, Chamber of Deputies", ListType.PEP),
        "ar_senado": ("PEP, Argentina, Senators", ListType.PEP),
        "br_chamber_deputies": ("PEP, Brazil, Chamber of Deputies", ListType.PEP),
        "br_federal_senate": ("PEP, Brazil, Senators", ListType.PEP),
        "cl_chamber_deputies": ("PEP, Chile, Chamber of Deputies", ListType.PEP),
        "cl_senate": ("PEP, Chile, Senators", ListType.PEP),
        "mx_deputies": ("PEP, Mexico, Chamber of Deputies", ListType.PEP),
        "mx_senators": ("PEP, Mexico, Senators", ListType.PEP),
        "mx_governors": ("PEP, Mexico, Governors", ListType.PEP),
        "co_join_dots": ("PEP, Colombia, PEPs (Joining the Dots)", ListType.PEP),
        "pe_congreso": ("PEP, Peru, Congress", ListType.PEP),
        "ve_asamblea_nacional": ("PEP, Venezuela, National Assembly", ListType.PEP),
        "py_congreso": ("PEP, Paraguay, Congress", ListType.PEP),
        "pa_asamblea": ("PEP, Panama, National Assembly", ListType.PEP),
        "gt_congress": ("PEP, Guatemala, Congress", ListType.PEP),
        "ca_senate": ("PEP, Canada, Senators", ListType.PEP),
        "ca_foreign_reps": ("PEP: Foreign heads of mission in Canada", ListType.PEP),
        "au_parliament": ("PEP, Australia, Parliament", ListType.PEP),
        "nz_parliament": ("PEP, New Zealand, Parliament", ListType.PEP),
        "ky_parliament": ("PEP, Cayman Islands, Parliament", ListType.PEP),
        "ky_judicial": ("PEP, Cayman Islands, senior judicial officers", ListType.PEP),
        "cn_npc": ("PEP, China, National People's Congress deputies", ListType.PEP),
        "hk_legco": ("PEP, Hong Kong, Legislative Council", ListType.PEP),
        "hk_principal_officials": ("PEP, Hong Kong, principal officials", ListType.PEP),
        "mo_legislature": ("PEP, Macau, Legislative Assembly", ListType.PEP),
        "tw_legislature": ("PEP, Taiwan, Legislative Yuan", ListType.PEP),
        "jp_shugiin": ("PEP, Japan, House of Representatives", ListType.PEP),
        "jp_sangiin": ("PEP, Japan, House of Councillors", ListType.PEP),
        "kr_assembly": ("PEP, South Korea, National Assembly", ListType.PEP),
        "in_sansad": ("PEP, India, Lok and Rajya Sabha", ListType.PEP),
        "pk_na_members": ("PEP, Pakistan, National Assembly", ListType.PEP),
        "pk_senate_members": ("PEP, Pakistan, Senators", ListType.PEP),
        "sg_gov_dir": ("PEP, Singapore, government directory", ListType.PEP),
        "my_parliament": ("PEP, Malaysia, Parliament", ListType.PEP),
        "th_cabinet": ("PEP, Thailand, Cabinet", ListType.PEP),
        "vn_national_assembly": ("PEP, Vietnam, National Assembly", ListType.PEP),
        "mn_parliament": ("PEP, Mongolia, Parliament", ListType.PEP),
        "kz_senate": ("PEP, Kazakhstan, Senators", ListType.PEP),
        "uz_legislative_chamber": ("PEP, Uzbekistan, Legislative Chamber", ListType.PEP),
        "uz_senate": ("PEP, Uzbekistan, Senators", ListType.PEP),
        "kg_jogorku_kenesh": ("PEP, Kyrgyzstan, Jogorku Kenesh", ListType.PEP),
        "tj_majlisi_milli": ("PEP, Tajikistan, Majlisi Milli", ListType.PEP),
        "tm_mejlis": ("PEP, Turkmenistan, Mejlis", ListType.PEP),
        "by_council_republic": ("PEP, Belarus, Council of the Republic", ListType.PEP),
        "qa_shura_council": ("PEP, Qatar, Shura Council", ListType.PEP),
        "bh_nuwab": ("PEP, Bahrain, Council of Representatives", ListType.PEP),
        "bh_shura_council": ("PEP, Bahrain, Shura Council", ListType.PEP),
        "om_parliament": ("PEP, Oman, Majlis Oman", ListType.PEP),
        "eg_house_representatives": ("PEP, Egypt, House of Representatives", ListType.PEP),
        "ma_representatives": ("PEP, Morocco, House of Representatives", ListType.PEP),
        "ma_house_councillors": ("PEP, Morocco, House of Councillors", ListType.PEP),
        "dz_apn": ("PEP, Algeria, People's National Assembly", ListType.PEP),
        "dz_council_nation": ("PEP, Algeria, Council of the Nation", ListType.PEP),
        "tn_arp": ("PEP, Tunisia, Assembly of the Representatives", ListType.PEP),
        "ng_join_dots": ("PEP, Nigeria, PEPs and relatives (Joining the Dots)", ListType.PEP),
        "ke_national_assembly": ("PEP, Kenya, National Assembly", ListType.PEP),
        "ke_senate": ("PEP, Kenya, Senators", ListType.PEP),
        "gh_parliament": ("PEP, Ghana, Parliament", ListType.PEP),
        "za_pmg_legislators": ("PEP, South Africa, legislators", ListType.PEP),
        "ci_national_assembly": ("PEP, Côte d'Ivoire, National Assembly", ListType.PEP),
        "sn_assembly": ("PEP, Senegal, National Assembly", ListType.PEP),
        "cm_national_assembly": ("PEP, Cameroon, National Assembly", ListType.PEP),
        "cm_senate": ("PEP, Cameroon, Senate", ListType.PEP),
        "ci_senate": ("PEP, Côte d'Ivoire, Senate", ListType.PEP),
        "ng_chipper_peps": ("PEP, Nigeria, politically exposed persons (Chipper)", ListType.PEP),
        "ke_judiciary": ("PEP, Kenya, judges of the superior courts", ListType.PEP),
        "ug_parliament": ("PEP, Uganda, Parliament", ListType.PEP),
        "tz_bunge": ("PEP, Tanzania, National Assembly", ListType.PEP),
        "rw_parliament": ("PEP, Rwanda, Parliament", ListType.PEP),
        "et_hopr": ("PEP, Ethiopia, House of Peoples' Representatives", ListType.PEP),
        "za_mm_officials": ("PEP, South Africa, municipal leadership", ListType.PEP),
        "al_kuvendi": ("PEP, Albania, Parliament", ListType.PEP),
        "ba_parliament": ("PEP, Bosnia and Herzegovina, Parliamentary Assembly", ListType.PEP),
        "me_skupstina": ("PEP, Montenegro, Parliament", ListType.PEP),
        "xk_assembly": ("PEP, Kosovo, Assembly", ListType.PEP),
        "is_althingi": ("PEP, Iceland, Althingi", ListType.PEP),
        "sm_consiglio": ("PEP, San Marino, Grand and General Council", ListType.PEP),
        "ad_consell_general": ("PEP, Andorra, General Council", ListType.PEP),
        "be_flemish_parliament": ("PEP, Belgium, Flemish Parliament", ListType.PEP),
        "be_walloon_parliament": ("PEP, Belgium, Walloon Parliament", ListType.PEP),
        "de_abgeordnetenwatch": ("PEP, Germany, legislators (AbgeordnetenWatch)", ListType.PEP),
        "at_meine_abgeordneten": ("PEP, Austria, public officials", ListType.PEP),
        "si_zvezoskop": ("PEP, Slovenia, political officials", ListType.PEP),
        "sk_public_officials": ("PEP, Slovakia, public officials", ListType.PEP),
        "ro_fiu_declarations": ("PEP, Romania, FIU public officials", ListType.PEP),
        "hr_public_officials": ("PEP, Croatia, register of public officials", ListType.PEP),
        "ge_declarations": ("PEP, Georgia, officials' asset declarations", ListType.PEP),
        "se_soe": ("PEP, Sweden, state-owned enterprises leadership", ListType.PEP),
        "no_brreg": ("PEP, Norway, state-owned enterprises leadership", ListType.PEP),
        "us_plural_legislators": ("PEP, US, state legislators", ListType.PEP),
    }
)

SKIPPED_SCHEMAS = {"Vessel", "Airplane", "CryptoWallet", "Address", "Security"}


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(";") if v.strip()]


class _State:
    def __init__(self) -> None:
        self.index = _Index()
        self.loaded_at = 0.0
        self.errors: list[str] = []
        self.lock = threading.Lock()


_STATE = _State()


def _fetch(dataset: str, timeout: float) -> str:
    resp = httpx.get(
        URL.format(dataset=dataset),
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.content.decode("utf-8", errors="replace")


def _load(dataset: str, index: _Index, timeout: float, text: str | None = None) -> None:
    label, list_type = DATASETS.get(dataset, (dataset, ListType.SANCTION))
    if text is None:
        text = _fetch(dataset, timeout)
    before = len(index.entries)
    for row in csv.DictReader(io.StringIO(text)):
        schema = row.get("schema") or ""
        if schema in SKIPPED_SCHEMAS or not row.get("name"):
            continue
        is_person = schema == "Person"
        dobs = _split(row.get("birth_date"))
        countries = [c.upper() for c in _split(row.get("countries")) if len(c) == 2]
        entity = Entity(
            id=f"{dataset}:{row.get('id')}",
            type=EntityType.PERSON if is_person else EntityType.COMPANY,
            name=row["name"],
            aliases=_split(row.get("aliases"))[:30],
            birth_date=dobs[0] if dobs and is_person else None,
            nationalities=countries if is_person else [],
            jurisdiction=countries[0] if countries and not is_person else None,
        )
        index.add(
            ListedEntry(
                entity=entity,
                dataset=label,
                url=ENTITY_URL.format(id=row.get("id")),
                program=(_split(row.get("sanctions")) or [None])[0],
                details={
                    "countries": ", ".join(countries) or None,
                    "first_seen": row.get("first_seen") or None,
                },
                list_type=list_type,
            )
        )
    if len(index.entries) == before:
        raise ValueError(f"{dataset}: file downloaded but empty (list discontinued or renamed?)")


class OpenDatasetsConnector(BaseConnector):
    #: shared list index of this connector class (one per server instance)
    _state: _State = _STATE
    #: settings field holding the comma-separated OpenSanctions dataset names
    datasets_setting = "open_datasets"
    name = "open_watchlists"
    label = (
        "Watchlists: national sanctions and asset freezes, PEPs of 50+ parliaments and "
        "governments, regulators' enforcement and warnings, debarments, wanted notices"
    )
    kind = "screening"
    homepage = "https://www.opensanctions.org/datasets/"

    def _datasets(self) -> list[str]:
        value = getattr(self.settings, self.datasets_setting, "") or ""
        return [d.strip() for d in value.split(",") if d.strip()]

    def _index(self) -> _Index:
        with self._state.lock:
            if (
                not self._state.index.entries
                or time.time() - self._state.loaded_at > REFRESH_SECONDS
            ):
                fresh, errors = _Index(), []
                timeout = max(self.settings.http_timeout_seconds, 30.0)
                datasets = self._datasets()
                # Download all lists in parallel (I/O bound), then index them one by one.
                with ThreadPoolExecutor(max_workers=max(1, min(16, len(datasets)))) as pool:
                    futures = {d: pool.submit(_fetch, d, timeout) for d in datasets}
                for dataset, future in futures.items():
                    try:
                        _load(dataset, fresh, timeout, future.result())
                    except (httpx.HTTPError, csv.Error, ValueError) as exc:
                        errors.append(f"{dataset} unavailable ({exc})")
                if not fresh.entries:
                    raise ConnectorError(f"{self.label}: " + "; ".join(errors or ["no data"]))
                self._state.index, self._state.errors, self._state.loaded_at = (
                    fresh,
                    errors,
                    time.time(),
                )
            return self._state.index

    def prefetch(self) -> None:
        if not self._state.index.entries:
            threading.Thread(target=self._safe_index, daemon=True).start()

    def _safe_index(self) -> None:
        with contextlib.suppress(ConnectorError):  # errors are reported when screening runs
            self._index()

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type not in (EntityType.PERSON, EntityType.COMPANY):
            return []
        hits = []
        for entry in self._index().candidates(entity):
            result = match_entities(entity, entry.entity)
            if result.score < MIN_SCORE:
                continue
            listed = entry.entity
            hits.append(
                ScreeningHit(
                    entity_id=entity.id,
                    list_type=entry.list_type,
                    dataset=entry.dataset,
                    matched_name=listed.name,
                    score=result.score,
                    explanation=result.explanation,
                    details={
                        "program": entry.program,
                        "birth_date": listed.birth_date,
                        "nationalities": listed.nationalities or None,
                        **entry.details,
                        "source": "OpenSanctions bulk data (CC BY-NC 4.0)",
                    },
                    provenance=self.provenance(self.record_id(listed.id), entry.url),
                )
            )
        return hits

    def screen_many(self, entities: list[Entity]) -> list[ScreeningHit]:
        return [h for e in entities for h in self.screen(e)]


class OpenDatasetsExtendedConnector(OpenDatasetsConnector):
    """Second batch of watchlists (terrorism lists worldwide, more regulators and debarments,
    investigative datasets, PEPs outside Europe). Loaded in the background so it never delays
    the core screening: until it is ready, screening says so instead of waiting."""

    _state = _State()
    datasets_setting = "open_datasets_extended"
    name = "open_watchlists_extended"
    label = (
        "Extended watchlists: terrorism and national sanctions worldwide, regulators, "
        "debarments, investigations (Kremlin, Dossier Center, The Sentry…), PEPs outside Europe"
    )
    #: seconds a screening waits for the lists on a cold server before reporting them as loading
    wait_seconds = 25.0

    def _ready_index(self) -> _Index:
        state = self._state
        if state.index.entries and time.time() - state.loaded_at <= REFRESH_SECONDS:
            return state.index
        self.prefetch()
        deadline = time.time() + self.wait_seconds
        while time.time() < deadline:
            if state.index.entries:
                return state.index
            time.sleep(0.5)
        raise ConnectorError(
            f"{self.label}: still loading on this server, included from the next check"
        )

    def prefetch(self) -> None:
        state = self._state
        if not state.index.entries and not getattr(state, "loading", False):
            state.loading = True  # type: ignore[attr-defined]

            def run() -> None:
                try:
                    self._safe_index()
                finally:
                    state.loading = False  # type: ignore[attr-defined]

            threading.Thread(target=run, daemon=True).start()

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type not in (EntityType.PERSON, EntityType.COMPANY):
            return []
        self._ready_index()
        return super().screen(entity)
