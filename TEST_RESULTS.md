# Automated test results

Command: `./.venv/bin/python -m unittest discover -s tests -v`

Environment: existing project `.venv` (Python 3.14). Run on 2026-11-08. The suite completed with **86 tests, all passing** in 10.94 seconds. The system `python3` interpreter lacks Flask and was not used for the successful run. Some legacy tests emit Python `ResourceWarning`s for unclosed file/database handles; they did not fail the suite and remain a cleanup item. No live NASA request was made; NASA endpoints are patched in route tests.

Each row records the test identifier, the behavior its name exercises (expected), and the observed result.

| Test | Expected | Actual |
|---|---|---|
| `test_basic_endpoints_and_validation` | Verify basic endpoints and validation. | PASS |
| `test_debug_hidden_and_key_not_exposed` | Verify debug hidden and key not exposed. | PASS |
| `test_demo_anomalies_end_to_end` | Verify demo anomalies end to end. | PASS |
| `test_demo_is_labelled_and_removable` | Verify demo is labelled and removable. | PASS |
| `test_every_local_asset_referenced_by_a_page_is_served` | Verify every local asset referenced by a page is served. | PASS |
| `test_nrt_refresh_without_key` | Verify nrt refresh without key. | PASS |
| `test_upload_then_query_and_export` | Verify upload then query and export. | PASS |
| `test_constant_baseline_uses_noise_floor` | Verify constant baseline uses noise floor. | PASS |
| `test_daily_anomaly` | Verify daily anomaly. | PASS |
| `test_insufficient_baseline_not_scored` | Verify insufficient baseline not scored. | PASS |
| `test_low_coverage_months_excluded` | Verify low coverage months excluded. | PASS |
| `test_moving_average` | Verify moving average. | PASS |
| `test_platform_change_caveat` | Verify platform change caveat. | PASS |
| `test_small_count_noise_not_flagged` | Verify small count noise not flagged. | PASS |
| `test_spike_flagged_with_robust_score` | Verify spike flagged with robust score. | PASS |
| `test_assumed_coverage_is_flagged` | Verify assumed coverage is flagged. | PASS |
| `test_zero_vs_no_data_and_monthly` | Verify zero vs no data and monthly. | PASS |
| `test_matches_persisted_and_calendar_updated` | Verify matches persisted and calendar updated. | PASS |
| `test_too_large_range_refused` | Verify too large range refused. | PASS |
| `test_csv_multi_platform_and_sensor_detection` | Verify csv multi platform and sensor detection. | PASS |
| `test_exact_duplicates_skipped_but_nearby_points_kept` | Verify exact duplicates skipped but nearby points kept. | PASS |
| `test_invalid_records_rejected_with_reasons` | Verify invalid records rejected with reasons. | PASS |
| `test_json_and_geojson` | Verify json and geojson. | PASS |
| `test_persistence_and_idempotent_migration` | Verify persistence and idempotent migration. | PASS |
| `test_provenance_and_scope_separation` | Verify provenance and scope separation. | PASS |
| `test_shapefile_rejected_with_clear_error` | Verify shapefile rejected with clear error. | PASS |
| `test_unrecognised_satellite_kept_and_flagged` | Verify unrecognised satellite kept and flagged. | PASS |
| `test_utc_timestamp_normalisation_and_raw_metadata` | Verify utc timestamp normalisation and raw metadata. | PASS |
| `test_error_text_response_is_a_failure` | Verify error text response is a failure. | PASS |
| `test_failed_source_is_not_zero_and_key_not_leaked` | Verify failed source is not zero and key not leaked. | PASS |
| `test_nrt_coverage_counts_only_full_days` | Verify nrt coverage counts only full days. | PASS |
| `test_all_api_routes_complete_without_external_network` | Verify all api routes complete without external network. | PASS |
| `test_all_pages_and_local_assets_are_served` | Verify all pages and local assets are served. | PASS |
| `test_concurrent_import_limit_returns_retryable_status` | Verify concurrent import limit returns retryable status. | PASS |
| `test_malformed_json_and_csv_are_rejected_as_inputs` | Verify malformed json and csv are rejected as inputs. | PASS |
| `test_map_thinning_samples_matching_rows_instead_of_global_ids` | Verify map thinning samples matching rows instead of global ids. | PASS |
| `test_nonfinite_and_partial_query_values_return_clear_400` | Verify nonfinite and partial query values return clear 400. | PASS |
| `test_overview_counts_and_defaults_are_region_scoped` | Verify overview counts and defaults are region scoped. | PASS |
| `test_upload_limit_returns_json_error` | Verify upload limit returns json error. | PASS |
| `test_nearby_distinct_coordinates_both_survive` | Verify nearby distinct coordinates both survive. | PASS |
| `test_same_place_and_time_different_satellite_kept` | Verify same place and time different satellite kept. | PASS |
| `test_true_duplicate_with_different_formatting_removed` | Verify true duplicate with different formatting removed. | PASS |
| `test_close_pair_matches` | Verify close pair matches. | PASS |
| `test_confidence_not_merged` | Verify confidence not merged. | PASS |
| `test_daily_summary_separate_sensors` | Verify daily summary separate sensors. | PASS |
| `test_far_apart_no_match` | Verify far apart no match. | PASS |
| `test_invalid_and_duplicates` | Verify invalid and duplicates. | PASS |
| `test_many_to_one_preserved` | Verify many to one preserved. | PASS |
| `test_missing_values_flagged_not_dropped` | Verify missing values flagged not dropped. | PASS |
| `test_raw_rows_not_mutated` | Verify raw rows not mutated. | PASS |
| `test_time_window` | Verify time window. | PASS |
| `test_threshold_sensitivity_report_is_reproducible_and_caveated` | Verify threshold sensitivity report is reproducible and caveated. | PASS |
| `test_assumed_import_does_not_pollute_confirmed_baseline` | Verify assumed import does not pollute confirmed baseline. | PASS |
| `test_assumed_only_history_cannot_produce_anomalies` | Verify assumed only history cannot produce anomalies. | PASS |
| `test_same_data_with_declared_coverage_is_analysed` | Verify same data with declared coverage is analysed. | PASS |
| `test_all_four_states` | Verify all four states. | PASS |
| `test_assumed_zero_is_not_a_value_and_has_no_intensity` | Verify assumed zero is not a value and has no intensity. | PASS |
| `test_confirmed_beats_assumed_when_both_cover_a_day` | Verify confirmed beats assumed when both cover a day. | PASS |
| `test_coverage_quality_exposed_to_frontend_and_reports` | Verify coverage quality exposed to frontend and reports. | PASS |
| `test_monthly_view_separates_assumed_from_confirmed` | Verify monthly view separates assumed from confirmed. | PASS |
| `test_api_requires_valid_extent_and_stores_it` | Verify api requires valid extent and stores it. | PASS |
| `test_bbox_validation` | Verify bbox validation. | PASS |
| `test_declare_extent_for_legacy_import_endpoint` | Verify declare extent for legacy import endpoint. | PASS |
| `test_extent_is_declared_not_inferred_from_detections` | Verify extent is declared not inferred from detections. | PASS |
| `test_haryana_extent_covers_haryana_not_punjab` | Verify haryana extent covers haryana not punjab. | PASS |
| `test_import_history_exposes_extent` | Verify import history exposes extent. | PASS |
| `test_no_declared_extent_gives_no_regional_coverage` | Verify no declared extent gives no regional coverage. | PASS |
| `test_punjab_plus_haryana_extent_covers_both_parts` | Verify punjab plus haryana extent covers both parts. | PASS |
| `test_existing_database_upgrades_without_losing_data` | Verify existing database upgrades without losing data. | PASS |
| `test_legacy_import_gives_no_coverage_until_extent_declared` | Verify legacy import gives no coverage until extent declared. | PASS |
| `test_equal_sized_but_different_platform_sets_trigger_caveat` | Verify equal sized but different platform sets trigger caveat. | PASS |
| `test_heterogeneous_baseline_warned` | Verify heterogeneous baseline warned. | PASS |
| `test_identical_platform_sets_no_caveat` | Verify identical platform sets no caveat. | PASS |
| `test_monthly_anomaly_endpoint_exposes_platform_counts_and_notes` | Verify monthly anomaly endpoint exposes platform counts and notes. | PASS |
| `test_per_sensor_and_per_platform_counts_preserved` | Verify per sensor and per platform counts preserved. | PASS |
| `test_archive_and_nrt_same_detection_not_double_counted` | Verify archive and nrt same detection not double counted. | PASS |
| `test_both_source_references_remain_retrievable` | Verify both source references remain retrievable. | PASS |
| `test_demo_clear_removes_only_demo_and_cascades_links` | Verify demo clear removes only demo and cascades links. | PASS |
| `test_different_nearby_coordinates_stay_distinct` | Verify different nearby coordinates stay distinct. | PASS |
| `test_firms_error_csv_is_rejected_as_source_failure` | Verify firms error csv is rejected as source failure. | PASS |
| `test_firms_request_error_redacts_map_key` | Verify firms request error redacts map key. | PASS |
| `test_identical_demo_and_nasa_observations_coexist` | Verify identical demo and nasa observations coexist. | PASS |
| `test_map_bbox_and_upload_extension_are_validated` | Verify map bbox and upload extension are validated. | PASS |
| `test_per_source_values_preserved_when_sources_disagree` | Verify per source values preserved when sources disagree. | PASS |
| `test_reports_limit_source_counts_and_months_to_requested_region_period` | Verify reports limit source counts and months to requested region period. | PASS |
| `test_satellite_aliases_normalize_but_original_labels_survive` | Verify satellite aliases normalize but original labels survive. | PASS |
