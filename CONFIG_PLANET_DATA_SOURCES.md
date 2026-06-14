cat > /mnt/c/Users/emilb/Desktop/AGI/CORTEX++_QWEN/CONFIG_PLANET_DATA_SOURCES.md << 'EOF'
# CONFIG_PLANET_DATA_SOURCES.md
# PLANET – Approved Data Sources and Suggestion Policy

---

## 1. CLIMATE_GLOBAL_RISK_REVIEW
```json
{
  "axis": "CLIMATE_GLOBAL_RISK_REVIEW",
  "approved_sources": [
    {"id": "OPEN_METEO_CLIMATE", "type": "climate_api", "url": "https://api.open-meteo.com/v1/climate", "status": "trusted_open", "notes": "Free climate projections, JSON, без ключ."},
    {"id": "OPEN_METEO_ARCHIVE", "type": "weather_api", "url": "https://archive-api.open-meteo.com/v1/archive", "status": "trusted_open", "notes": "Исторически серии за времето, JSON, без ключ."},
    {"id": "OPEN_METEO_FORECAST", "type": "weather_api", "url": "https://api.open-meteo.com/v1/forecast", "status": "trusted_open", "notes": "Краткосрочни прогнози за температура, валежи, вятър."},
    {"id": "OPENWEATHERMAP_ONECALL", "type": "weather_api", "url": "https://api.openweathermap.org/data/3.0/onecall", "status": "use_with_caution", "notes": "Глобални данни за времето, изисква API ключ."},
    {"id": "OPENWEATHERMAP_AIR_POLLUTION", "type": "air_quality_api", "url": "https://api.openweathermap.org/data/2.5/air_pollution", "status": "use_with_caution", "notes": "PM2.5, PM10, O3, AQI, изисква API ключ."},
    {"id": "NOAA_GML_CO2", "type": "co2_api", "url": "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_weekly_mlo.csv", "status": "trusted_open", "notes": "Mauna Loa CO2 седмични данни, CSV, без ключ. РАБОТИ в WSL2."},
    {"id": "NOAA_GML_CO2_ANNUAL", "type": "co2_api", "url": "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.csv", "status": "trusted_open", "notes": "Mauna Loa CO2 годишни средни, CSV, без ключ. РАБОТИ в WSL2."},
    {"id": "NOAA_CDO_API", "type": "climate_api", "url": "https://www.ncdc.noaa.gov/cdo-web/webservices/v2", "status": "use_with_caution", "notes": "Climate Data Online, изисква token."},
    {"id": "NOAA_REANALYSIS_DATASETS", "type": "reanalysis_dataset", "url": "https://psl.noaa.gov/data/gridded/reanalysis/", "status": "use_with_caution", "notes": "ERA5, NCEP reanalysis полета."},
    {"id": "COPERNICUS_CDS_API", "type": "reanalysis_dataset", "url": "https://cds.climate.copernicus.eu/api-how-to", "status": "use_with_caution", "notes": "ERA5 от ECMWF, изисква регистрация."},
    {"id": "WORLD_BANK_CLIMATE_API", "type": "climate_indicators_api", "url": "https://climateknowledgeportal.worldbank.org/api", "status": "trusted_open", "notes": "Климатични индикатори по държави, JSON, без ключ."},
    {"id": "CLIMATE_TRACE_API", "type": "emissions_api", "url": "https://climatetrace.org/data", "status": "use_with_caution", "notes": "GHG емисии по сектори."},
    {"id": "EKAGNI_CLIMATE_API", "type": "climate_api", "url": "https://ekagni.com/api/climate-api.html", "status": "use_with_caution", "notes": "Климатични данни и прогнози, REST API."}
  ],
  "suggested_for_approval": []
}
```
EOF