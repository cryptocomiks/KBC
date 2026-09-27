"""Application settings, read from environment variables and the `.env` file."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def _default_cache_path() -> str:
    # Vercel's filesystem is read-only except /tmp (ephemeral, which is fine for a cache).
    if os.environ.get("VERCEL"):
        return "/tmp/kbc_cache.db"
    return str(REPO_ROOT / "data" / "kbc_cache.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # An empty variable (e.g. DEMO_MODE= copied from .env.example) means "use the default".
        env_ignore_empty=True,
    )

    # Fictitious demo dataset (always separate from real data)
    demo_mode: bool = True
    # Real sources: keyless public APIs are on by default, keyed ones need their key
    live_sources: bool = True
    cache_path: str = _default_cache_path()
    cache_ttl_hours: int = 72

    # Cases, analyst decisions and monitoring history (durable store). On Vercel, create a
    # Postgres database (Storage tab): it injects DATABASE_URL / POSTGRES_URL. Without it,
    # a local SQLite file is used (ephemeral on Vercel).
    database_url: str = Field(
        default="", validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL")
    )
    store_path: str = (
        "/tmp/kbc_store.db"
        if os.environ.get("VERCEL")
        else str(REPO_ROOT / "data" / "kbc_store.db")
    )
    # Password protecting cases and the dashboard (required on Vercel to use cases).
    app_password: str = ""
    # Secret for the monitoring job (GitHub Actions / Vercel Cron) that refreshes cases.
    cron_secret: str = ""

    pappers_api_key: str = ""
    opencorporates_api_token: str = ""
    companies_house_api_key: str = ""
    aleph_api_key: str = ""
    opensanctions_api_key: str = ""
    # The Guardian Open Platform (free developer key): second adverse-media source
    guardian_api_key: str = ""
    # Open watchlists downloaded as bulk files (OpenSanctions dataset names, comma-separated)
    open_datasets: str = (
        "eu_fsf,gb_fcdo_sanctions,ch_seco_sanctions,ca_dfatd_sema_sanctions,au_dfat_sanctions,"
        "jp_mof_sanctions,worldbank_debarred,interpol_red_notices,"
        "ru_acf_bribetakers,ua_war_sanctions,wd_oligarchs,gb_coh_disqualified,ch_finma_warnings,"
        "be_fod_sanctions,nz_russia_sanctions,lv_magnitsky_list,ru_navalny35,afdb_sanctions,"
        "adb_sanctions,iadb_sanctions,ebrd_ineligible,eu_edes,lu_administrative_sanctions,"
        "ch_finma_rulings,fr_amf_regulatory_sanctions,fr_illegal_financial_services,eu_esma_sanctions,"
        "us_sec_pause,no_nbim_exclusions,fr_hatvp_declarations,eu_europol_wanted,gb_nca_most_wanted,"
        "gb_nca_press_releases,us_fbi_most_wanted,de_bka_wanted,"
        "fr_tresor_gels_avoir,mc_fund_freezes,ch_fiaa_freezes,eu_travel_bans,"
        "ee_international_sanctions,lv_fiu_sanctions,lt_magnitsky_amendments,pl_mswia_sanctions,"
        "cz_national_sanctions,ca_facfoa,us_klepto_hr_visa,us_bis_denied,us_fincen_special_measures,"
        "tr_fcib,za_fic_sanctions,jp_meti_ru,us_fincen_enforcement,us_ofac_enforcement_actions,"
        "us_cftc_enforcement_actions,us_nfa_enforcement_actions,us_finra_barred,us_ddtc_debarred,"
        "ae_dfsa_prohibited,my_consumer_alert_list,lt_illegal_websites,"
        "hk_icac_wanted,us_dea_fugitives,"
        # Politically exposed persons (national parliaments, governments, world leaders)
        "us_cia_world_leaders,un_ga_protocol,eu_meps,eu_cor_members,"
        "fr_assemblee,fr_senat,mc_conseil_national,ch_parlament,li_landtag,lu_chamber,"
        "lu_bourgmestres,be_chamber,be_senate,nl_house_of_representatives,nl_senate,"
        "de_bundestag,de_bundesrat,at_parlament,it_deputies,it_senate,es_parliament,"
        "pt_parliament,gb_commons,gb_lords,ie_parliament,mt_parlament,cy_parliament,"
        "gr_parliament,dk_pep,se_riksdag,no_storting,fi_eduskunta,ee_riigikogu,lv_saeima,"
        "lt_seimas,pl_sejm,pl_senate,cz_pep_declarations,sk_nrsr_poslanci,hu_national_assembly,"
        "si_dz_rs,hr_sabor,ro_cdep_deputies,ro_senate,bg_parliament,rs_national_assembly,"
        "ua_rada,ru_duma_deputies,ru_federation_council,ge_parliament,am_national_assembly,"
        "az_parliament,kz_mazhilis,tr_parliament,il_knesset_members,us_congress,us_state_dept,"
        "ca_commons"
    )
    # casinosecrets.lol went offline in Sept 2026 (the domain no longer resolves): set to true
    # to query it again if the consortium republishes it at the same address.
    casino_secrets_enabled: bool = False
    # Second batch of watchlists, loaded in the background (never delays the core screening)
    open_datasets_extended: str = (
        "ua_nsdc_sanctions,ua_sfms_blacklist,us_ofac_cons,us_state_terrorist_orgs,"
        "us_state_terrorist_exclusion,us_cuba_sanctions,us_dhs_uflpa,us_bis_mieu,"
        "us_cbp_forced_labor,us_nk_jointventures,us_dod_chinese_milcorps,us_fcc_covered_list,"
        "gb_proscribed_orgs,ca_listed_terrorists,au_listed_terrorist_orgs,"
        "nz_designated_terrorists,nl_terrorism_list,cz_terrorists,at_nbter_sanctions,"
        "lt_fiu_freezes,pl_finanse_sanctions,ro_onpcsb_sanctions,bg_mft_national,"
        "rs_apml_domestic,md_terror_sanctions,ge_ot_list,az_fiu_sanctions,kg_fiu_national,"
        "il_mod_terrorists,il_wmd_sanctions,ae_local_terrorists,qa_nctc_sanctions,"
        "sa_pcct_terrorism_list,jo_sanctions,iq_aml_list,eg_terrorists,tn_cnlct,"
        "ke_frc_sanctions,ng_nigsac_sanctions,in_mha_banned,pk_proscribed_persons,"
        "np_mha_sanctions,id_dttot,my_moha_sanctions,sg_terrorists,th_designated_person,"
        "ph_amlc_sanctions,vn_terrorist_orgs,ps_local_freezing,ar_repet,de_bfv_extremism,"
        "ie_unlawful_organizations,jp_meti_eul,us_fed_enforcements,us_occ_enfact,us_bis_export,"
        "us_bis_antiboycott,us_ddtc_enforcements,us_sec_harmed_investors,us_special_leg,"
        "gg_disqualified_directors,im_disqualified_directors,tr_cmb_banned,in_nse_debarred,"
        "my_aob_sanctions,my_investor_alert_list,ph_sec_advisories,ph_gppb_debarred,br_ceis,"
        "br_tcu_debarred,br_bcb_disqualified_persons,md_interdictie,si_conflicts,"
        "lt_illegal_gambling,li_entsg,br_slavery,ru_dossier_center_poi,ru_kremlin_persons,"
        "ru_billionaires_2021,md_rise_profiles,thesentry_atlas,ir_uani_business_registry,"
        "shu_uyghur_companies,c4ads_xinjiang,ps_ohchr_settlement,tr_wanted,es_cnp_wanted,"
        "nl_most_wanted,us_ice_wanted,us_ss_wanted,za_wanted,ar_parliament,ar_senado,"
        "br_chamber_deputies,br_federal_senate,cl_chamber_deputies,cl_senate,mx_deputies,"
        "mx_senators,mx_governors,co_join_dots,pe_congreso,ve_asamblea_nacional,py_congreso,"
        "pa_asamblea,gt_congress,ca_senate,ca_foreign_reps,au_parliament,nz_parliament,"
        "ky_parliament,ky_judicial,cn_npc,hk_legco,hk_principal_officials,mo_legislature,"
        "tw_legislature,jp_shugiin,jp_sangiin,kr_assembly,in_sansad,pk_na_members,"
        "pk_senate_members,sg_gov_dir,my_parliament,th_cabinet,vn_national_assembly,"
        "mn_parliament,kz_senate,uz_legislative_chamber,uz_senate,kg_jogorku_kenesh,"
        "tj_majlisi_milli,tm_mejlis,by_council_republic,qa_shura_council,bh_nuwab,"
        "bh_shura_council,om_parliament,eg_house_representatives,ma_representatives,"
        "ma_house_councillors,dz_apn,dz_council_nation,tn_arp,ng_join_dots,ke_national_assembly,"
        "ke_senate,gh_parliament,za_pmg_legislators,ci_national_assembly,sn_assembly,"
        "cm_national_assembly,al_kuvendi,ba_parliament,me_skupstina,xk_assembly,is_althingi,"
        "sm_consiglio,ad_consell_general,be_flemish_parliament,be_walloon_parliament,"
        "de_abgeordnetenwatch,at_meine_abgeordneten,si_zvezoskop,sk_public_officials,"
        "ro_fiu_declarations,hr_public_officials,ge_declarations,se_soe,no_brreg,"
        "us_plural_legislators"
    )
    icij_db_path: str = str(REPO_ROOT / "data" / "icij_offshore_leaks.db")

    risk_config_path: str = str(CONFIG_DIR / "risk.yaml")
    jurisdictions_config_path: str = str(CONFIG_DIR / "jurisdictions.yaml")
    country_risk_path: str = str(CONFIG_DIR / "country_risk.json")
    # The SEC blocks automated requests whose User-Agent does not name a contact.
    sec_user_agent: str = "KYC1Click research-contact@kbc-mapping.org"

    # Guard rails for network expansion
    max_depth: int = 3
    max_nodes_limit: int = 250
    http_timeout_seconds: float = 15.0
    # Wall-clock budget for one investigation over live APIs (serverless time limits)
    expansion_time_budget_seconds: float = 150.0
    screening_workers: int = 6
    # Registry calls issued ahead, in parallel, while the network expands
    expansion_workers: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
