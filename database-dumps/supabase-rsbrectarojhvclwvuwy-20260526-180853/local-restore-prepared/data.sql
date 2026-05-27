--
-- PostgreSQL database dump
--


-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.10

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: audit_log_entries; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."audit_log_entries" ("instance_id", "id", "payload", "created_at", "ip_address") FROM stdin;
\.


--
-- Data for Name: custom_oauth_providers; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."custom_oauth_providers" ("id", "provider_type", "identifier", "name", "client_id", "client_secret", "acceptable_client_ids", "scopes", "pkce_enabled", "attribute_mapping", "authorization_params", "enabled", "email_optional", "issuer", "discovery_url", "skip_nonce_check", "cached_discovery", "discovery_cached_at", "authorization_url", "token_url", "userinfo_url", "jwks_uri", "created_at", "updated_at") FROM stdin;
\.


--
-- Data for Name: flow_state; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."flow_state" ("id", "user_id", "auth_code", "code_challenge_method", "code_challenge", "provider_type", "provider_access_token", "provider_refresh_token", "created_at", "updated_at", "authentication_method", "auth_code_issued_at", "invite_token", "referrer", "oauth_client_state_id", "linking_target_id", "email_optional") FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."users" ("instance_id", "id", "aud", "role", "email", "encrypted_password", "email_confirmed_at", "invited_at", "confirmation_token", "confirmation_sent_at", "recovery_token", "recovery_sent_at", "email_change_token_new", "email_change", "email_change_sent_at", "last_sign_in_at", "raw_app_meta_data", "raw_user_meta_data", "is_super_admin", "created_at", "updated_at", "phone", "phone_confirmed_at", "phone_change", "phone_change_token", "phone_change_sent_at", "email_change_token_current", "email_change_confirm_status", "banned_until", "reauthentication_token", "reauthentication_sent_at", "is_sso_user", "deleted_at", "is_anonymous") FROM stdin;
00000000-0000-0000-0000-000000000000	16a1c2a4-6116-48d5-aeb6-e278d694e156	authenticated	authenticated	sean.balbale@gmail.com	$2a$10$tOXUWlb8hLwmrA7ohNqScOBpEnWDoAqC4NXq3Nr81W4YQh3x9bWmO	2026-04-27 20:35:31.1262+00	\N		\N		\N			\N	2026-04-27 22:19:15.765353+00	{"provider": "email", "providers": ["email"]}	{"email_verified": true}	\N	2026-04-27 20:35:31.095262+00	2026-04-27 22:19:15.768404+00	\N	\N			\N		0	\N		\N	f	\N	f
\.


--
-- Data for Name: identities; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."identities" ("provider_id", "user_id", "identity_data", "provider", "last_sign_in_at", "created_at", "updated_at", "id") FROM stdin;
16a1c2a4-6116-48d5-aeb6-e278d694e156	16a1c2a4-6116-48d5-aeb6-e278d694e156	{"sub": "16a1c2a4-6116-48d5-aeb6-e278d694e156", "email": "sean.balbale@gmail.com", "email_verified": false, "phone_verified": false}	email	2026-04-27 20:35:31.117768+00	2026-04-27 20:35:31.117827+00	2026-04-27 20:35:31.117827+00	c9519be8-c060-4577-a448-3d5e4e4f0815
\.


--
-- Data for Name: instances; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."instances" ("id", "uuid", "raw_base_config", "created_at", "updated_at") FROM stdin;
\.


--
-- Data for Name: oauth_clients; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."oauth_clients" ("id", "client_secret_hash", "registration_type", "redirect_uris", "grant_types", "client_name", "client_uri", "logo_uri", "created_at", "updated_at", "deleted_at", "client_type", "token_endpoint_auth_method") FROM stdin;
\.


--
-- Data for Name: sessions; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."sessions" ("id", "user_id", "created_at", "updated_at", "factor_id", "aal", "not_after", "refreshed_at", "user_agent", "ip", "tag", "oauth_client_id", "refresh_token_hmac_key", "refresh_token_counter", "scopes") FROM stdin;
e839d20a-78d6-44d1-92ae-b769f28e065f	16a1c2a4-6116-48d5-aeb6-e278d694e156	2026-04-27 22:19:15.765476+00	2026-04-27 22:19:15.765476+00	\N	aal1	\N	\N	Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36	73.253.149.160	\N	\N	\N	\N	\N
\.


--
-- Data for Name: mfa_amr_claims; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."mfa_amr_claims" ("session_id", "created_at", "updated_at", "authentication_method", "id") FROM stdin;
e839d20a-78d6-44d1-92ae-b769f28e065f	2026-04-27 22:19:15.768855+00	2026-04-27 22:19:15.768855+00	password	74e57d0a-8799-41ae-8c7c-9becd25128ac
\.


--
-- Data for Name: mfa_factors; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."mfa_factors" ("id", "user_id", "friendly_name", "factor_type", "status", "created_at", "updated_at", "secret", "phone", "last_challenged_at", "web_authn_credential", "web_authn_aaguid", "last_webauthn_challenge_data") FROM stdin;
\.


--
-- Data for Name: mfa_challenges; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."mfa_challenges" ("id", "factor_id", "created_at", "verified_at", "ip_address", "otp_code", "web_authn_session_data") FROM stdin;
\.


--
-- Data for Name: oauth_authorizations; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."oauth_authorizations" ("id", "authorization_id", "client_id", "user_id", "redirect_uri", "scope", "state", "resource", "code_challenge", "code_challenge_method", "response_type", "status", "authorization_code", "created_at", "expires_at", "approved_at", "nonce") FROM stdin;
\.


--
-- Data for Name: oauth_client_states; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."oauth_client_states" ("id", "provider_type", "code_verifier", "created_at") FROM stdin;
\.


--
-- Data for Name: oauth_consents; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."oauth_consents" ("id", "user_id", "client_id", "scopes", "granted_at", "revoked_at") FROM stdin;
\.


--
-- Data for Name: one_time_tokens; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."one_time_tokens" ("id", "user_id", "token_type", "token_hash", "relates_to", "created_at", "updated_at") FROM stdin;
\.


--
-- Data for Name: refresh_tokens; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."refresh_tokens" ("instance_id", "id", "token", "user_id", "revoked", "created_at", "updated_at", "parent", "session_id") FROM stdin;
00000000-0000-0000-0000-000000000000	4	ndmqh55efekn	16a1c2a4-6116-48d5-aeb6-e278d694e156	f	2026-04-27 22:19:15.767201+00	2026-04-27 22:19:15.767201+00	\N	e839d20a-78d6-44d1-92ae-b769f28e065f
\.


--
-- Data for Name: sso_providers; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."sso_providers" ("id", "resource_id", "created_at", "updated_at", "disabled") FROM stdin;
\.


--
-- Data for Name: saml_providers; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."saml_providers" ("id", "sso_provider_id", "entity_id", "metadata_xml", "metadata_url", "attribute_mapping", "created_at", "updated_at", "name_id_format") FROM stdin;
\.


--
-- Data for Name: saml_relay_states; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."saml_relay_states" ("id", "sso_provider_id", "request_id", "for_email", "redirect_to", "created_at", "updated_at", "flow_state_id") FROM stdin;
\.


--
-- Data for Name: schema_migrations; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."schema_migrations" ("version") FROM stdin;
20171026211738
20171026211808
20171026211834
20180103212743
20180108183307
20180119214651
20180125194653
00
20210710035447
20210722035447
20210730183235
20210909172000
20210927181326
20211122151130
20211124214934
20211202183645
20220114185221
20220114185340
20220224000811
20220323170000
20220429102000
20220531120530
20220614074223
20220811173540
20221003041349
20221003041400
20221011041400
20221020193600
20221021073300
20221021082433
20221027105023
20221114143122
20221114143410
20221125140132
20221208132122
20221215195500
20221215195800
20221215195900
20230116124310
20230116124412
20230131181311
20230322519590
20230402418590
20230411005111
20230508135423
20230523124323
20230818113222
20230914180801
20231027141322
20231114161723
20231117164230
20240115144230
20240214120130
20240306115329
20240314092811
20240427152123
20240612123726
20240729123726
20240802193726
20240806073726
20241009103726
20250717082212
20250731150234
20250804100000
20250901200500
20250903112500
20250904133000
20250925093508
20251007112900
20251104100000
20251111201300
20251201000000
20260115000000
20260121000000
20260219120000
20260302000000
\.


--
-- Data for Name: sso_domains; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."sso_domains" ("id", "sso_provider_id", "domain", "created_at", "updated_at") FROM stdin;
\.


--
-- Data for Name: webauthn_challenges; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."webauthn_challenges" ("id", "user_id", "challenge_type", "session_data", "created_at", "expires_at") FROM stdin;
\.


--
-- Data for Name: webauthn_credentials; Type: TABLE DATA; Schema: auth; Owner: supabase_auth_admin
--

COPY "auth"."webauthn_credentials" ("id", "user_id", "credential_id", "public_key", "attestation_type", "aaguid", "sign_count", "transports", "backup_eligible", "backed_up", "friendly_name", "created_at", "updated_at", "last_used_at") FROM stdin;
\.


--
-- Data for Name: athletes; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY "public"."athletes" ("id", "ftp", "max_hr", "created_at", "display_name", "weight_kg", "height_cm") FROM stdin;
16a1c2a4-6116-48d5-aeb6-e278d694e156	250	204	2026-04-27 21:05:24.93446+00	Sean	\N	\N
\.


--
-- Data for Name: biometrics; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY "public"."biometrics" ("id", "athlete_id", "record_date", "hrv", "resting_hr", "sleep_score", "created_at") FROM stdin;
\.


--
-- Data for Name: coach_memories; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY "public"."coach_memories" ("id", "athlete_id", "content", "embedding", "created_at") FROM stdin;
\.


--
-- Data for Name: oauth_tokens; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY "public"."oauth_tokens" ("id", "athlete_id", "provider", "access_token", "refresh_token", "expires_at", "external_user_id", "created_at", "updated_at") FROM stdin;
65f9cdf5-023b-4122-9bf1-0215adc64182	16a1c2a4-6116-48d5-aeb6-e278d694e156	whoop	5ZFx_RPgpUMU37CoO5gDptKstbo5_BkoH_fTdnIK9lw.-6aiNgH8eK-mPYTQMeRlLuYXQJd8F2L6BK_qRPkfQkE	Z0w7hqha_7gdamEiL9kQEGb-ul0bJBeWi2jnllOVVrI.Q7N-Ii7juDkVtx1BwT0l40Tq6_vVWs0CJzimtPIoF1Y	\N	2232326	2026-04-27 21:08:22.83503+00	2026-04-27 21:08:22.83503+00
\.


--
-- Data for Name: training_plans; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY "public"."training_plans" ("id", "athlete_id", "planned_date", "sport", "title", "description", "duration_min", "target_tss", "status", "created_at") FROM stdin;
\.


--
-- Data for Name: tss_history; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY "public"."tss_history" ("id", "athlete_id", "record_date", "daily_tss", "ctl", "atl", "tsb") FROM stdin;
\.


--
-- Data for Name: workouts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY "public"."workouts" ("id", "athlete_id", "source", "workout_type", "start_time", "duration_seconds", "tss", "normalized_power", "average_hr", "created_at") FROM stdin;
\.


--
-- Data for Name: schema_migrations; Type: TABLE DATA; Schema: realtime; Owner: supabase_admin
--

COPY "realtime"."schema_migrations" ("version", "inserted_at") FROM stdin;
20211116024918	2026-04-27 01:08:56
20211116045059	2026-04-27 01:08:56
20211116050929	2026-04-27 01:08:56
20211116051442	2026-04-27 01:08:56
20211116212300	2026-04-27 01:08:56
20211116213355	2026-04-27 01:08:56
20211116213934	2026-04-27 01:08:57
20211116214523	2026-04-27 01:08:57
20211122062447	2026-04-27 01:08:57
20211124070109	2026-04-27 01:08:57
20211202204204	2026-04-27 01:08:57
20211202204605	2026-04-27 01:08:57
20211210212804	2026-04-27 01:08:58
20211228014915	2026-04-27 01:08:58
20220107221237	2026-04-27 01:08:58
20220228202821	2026-04-27 01:08:58
20220312004840	2026-04-27 01:08:58
20220603231003	2026-04-27 01:08:58
20220603232444	2026-04-27 01:08:58
20220615214548	2026-04-27 01:08:59
20220712093339	2026-04-27 01:08:59
20220908172859	2026-04-27 01:08:59
20220916233421	2026-04-27 01:08:59
20230119133233	2026-04-27 01:08:59
20230128025114	2026-04-27 01:08:59
20230128025212	2026-04-27 01:08:59
20230227211149	2026-04-27 01:09:00
20230228184745	2026-04-27 01:09:00
20230308225145	2026-04-27 01:09:00
20230328144023	2026-04-27 01:09:00
20231018144023	2026-04-27 01:09:00
20231204144023	2026-04-27 01:09:00
20231204144024	2026-04-27 01:09:00
20231204144025	2026-04-27 01:09:01
20240108234812	2026-04-27 01:09:01
20240109165339	2026-04-27 01:09:01
20240227174441	2026-04-27 01:09:01
20240311171622	2026-04-27 01:09:01
20240321100241	2026-04-27 01:09:01
20240401105812	2026-04-27 01:09:02
20240418121054	2026-04-27 01:09:02
20240523004032	2026-04-27 01:09:02
20240618124746	2026-04-27 01:09:03
20240801235015	2026-04-27 01:09:03
20240805133720	2026-04-27 01:09:03
20240827160934	2026-04-27 01:09:03
20240919163303	2026-04-27 01:09:03
20240919163305	2026-04-27 01:09:03
20241019105805	2026-04-27 01:09:03
20241030150047	2026-04-27 01:09:04
20241108114728	2026-04-27 01:09:04
20241121104152	2026-04-27 01:09:04
20241130184212	2026-04-27 01:09:04
20241220035512	2026-04-27 01:09:04
20241220123912	2026-04-27 01:09:05
20241224161212	2026-04-27 01:09:05
20250107150512	2026-04-27 01:09:05
20250110162412	2026-04-27 01:09:05
20250123174212	2026-04-27 01:09:05
20250128220012	2026-04-27 01:09:05
20250506224012	2026-04-27 01:09:05
20250523164012	2026-04-27 01:09:05
20250714121412	2026-04-27 01:09:06
20250905041441	2026-04-27 01:09:06
20251103001201	2026-04-27 01:09:06
20251120212548	2026-04-27 01:09:06
20251120215549	2026-04-27 01:09:06
20260218120000	2026-04-27 01:09:06
20260326120000	2026-04-27 01:09:06
\.


--
-- Data for Name: subscription; Type: TABLE DATA; Schema: realtime; Owner: supabase_admin
--

COPY "realtime"."subscription" ("id", "subscription_id", "entity", "filters", "claims", "created_at", "action_filter") FROM stdin;
\.


--
-- Data for Name: buckets; Type: TABLE DATA; Schema: storage; Owner: supabase_storage_admin
--

COPY "storage"."buckets" ("id", "name", "owner", "created_at", "updated_at", "public", "avif_autodetection", "file_size_limit", "allowed_mime_types", "owner_id", "type") FROM stdin;
\.


--
-- Data for Name: buckets_analytics; Type: TABLE DATA; Schema: storage; Owner: supabase_storage_admin
--

COPY "storage"."buckets_analytics" ("name", "type", "format", "created_at", "updated_at", "id", "deleted_at") FROM stdin;
\.


--
-- Data for Name: buckets_vectors; Type: TABLE DATA; Schema: storage; Owner: supabase_storage_admin
--

COPY "storage"."buckets_vectors" ("id", "type", "created_at", "updated_at") FROM stdin;
\.


--
-- Data for Name: migrations; Type: TABLE DATA; Schema: storage; Owner: supabase_storage_admin
--

COPY "storage"."migrations" ("id", "name", "hash", "executed_at") FROM stdin;
0	create-migrations-table	e18db593bcde2aca2a408c4d1100f6abba2195df	2026-04-27 01:04:26.674126
1	initialmigration	6ab16121fbaa08bbd11b712d05f358f9b555d777	2026-04-27 01:04:26.697998
2	storage-schema	f6a1fa2c93cbcd16d4e487b362e45fca157a8dbd	2026-04-27 01:04:26.700475
3	pathtoken-column	2cb1b0004b817b29d5b0a971af16bafeede4b70d	2026-04-27 01:04:26.7153
4	add-migrations-rls	427c5b63fe1c5937495d9c635c263ee7a5905058	2026-04-27 01:04:26.723077
5	add-size-functions	79e081a1455b63666c1294a440f8ad4b1e6a7f84	2026-04-27 01:04:26.725976
6	change-column-name-in-get-size	ded78e2f1b5d7e616117897e6443a925965b30d2	2026-04-27 01:04:26.729817
7	add-rls-to-buckets	e7e7f86adbc51049f341dfe8d30256c1abca17aa	2026-04-27 01:04:26.733224
8	add-public-to-buckets	fd670db39ed65f9d08b01db09d6202503ca2bab3	2026-04-27 01:04:26.736287
9	fix-search-function	af597a1b590c70519b464a4ab3be54490712796b	2026-04-27 01:04:26.739195
10	search-files-search-function	b595f05e92f7e91211af1bbfe9c6a13bb3391e16	2026-04-27 01:04:26.741852
11	add-trigger-to-auto-update-updated_at-column	7425bdb14366d1739fa8a18c83100636d74dcaa2	2026-04-27 01:04:26.745054
12	add-automatic-avif-detection-flag	8e92e1266eb29518b6a4c5313ab8f29dd0d08df9	2026-04-27 01:04:26.748165
13	add-bucket-custom-limits	cce962054138135cd9a8c4bcd531598684b25e7d	2026-04-27 01:04:26.751744
14	use-bytes-for-max-size	941c41b346f9802b411f06f30e972ad4744dad27	2026-04-27 01:04:26.754754
15	add-can-insert-object-function	934146bc38ead475f4ef4b555c524ee5d66799e5	2026-04-27 01:04:26.77386
16	add-version	76debf38d3fd07dcfc747ca49096457d95b1221b	2026-04-27 01:04:26.776722
17	drop-owner-foreign-key	f1cbb288f1b7a4c1eb8c38504b80ae2a0153d101	2026-04-27 01:04:26.779316
18	add_owner_id_column_deprecate_owner	e7a511b379110b08e2f214be852c35414749fe66	2026-04-27 01:04:26.78225
19	alter-default-value-objects-id	02e5e22a78626187e00d173dc45f58fa66a4f043	2026-04-27 01:04:26.786743
20	list-objects-with-delimiter	cd694ae708e51ba82bf012bba00caf4f3b6393b7	2026-04-27 01:04:26.789632
21	s3-multipart-uploads	8c804d4a566c40cd1e4cc5b3725a664a9303657f	2026-04-27 01:04:26.793756
22	s3-multipart-uploads-big-ints	9737dc258d2397953c9953d9b86920b8be0cdb73	2026-04-27 01:04:26.809185
23	optimize-search-function	9d7e604cddc4b56a5422dc68c9313f4a1b6f132c	2026-04-27 01:04:26.817981
24	operation-function	8312e37c2bf9e76bbe841aa5fda889206d2bf8aa	2026-04-27 01:04:26.820747
25	custom-metadata	d974c6057c3db1c1f847afa0e291e6165693b990	2026-04-27 01:04:26.823481
26	objects-prefixes	215cabcb7f78121892a5a2037a09fedf9a1ae322	2026-04-27 01:04:26.826565
27	search-v2	859ba38092ac96eb3964d83bf53ccc0b141663a6	2026-04-27 01:04:26.828936
28	object-bucket-name-sorting	c73a2b5b5d4041e39705814fd3a1b95502d38ce4	2026-04-27 01:04:26.831169
29	create-prefixes	ad2c1207f76703d11a9f9007f821620017a66c21	2026-04-27 01:04:26.833258
30	update-object-levels	2be814ff05c8252fdfdc7cfb4b7f5c7e17f0bed6	2026-04-27 01:04:26.835421
31	objects-level-index	b40367c14c3440ec75f19bbce2d71e914ddd3da0	2026-04-27 01:04:26.837426
32	backward-compatible-index-on-objects	e0c37182b0f7aee3efd823298fb3c76f1042c0f7	2026-04-27 01:04:26.839513
33	backward-compatible-index-on-prefixes	b480e99ed951e0900f033ec4eb34b5bdcb4e3d49	2026-04-27 01:04:26.841427
34	optimize-search-function-v1	ca80a3dc7bfef894df17108785ce29a7fc8ee456	2026-04-27 01:04:26.843386
35	add-insert-trigger-prefixes	458fe0ffd07ec53f5e3ce9df51bfdf4861929ccc	2026-04-27 01:04:26.84558
36	optimise-existing-functions	6ae5fca6af5c55abe95369cd4f93985d1814ca8f	2026-04-27 01:04:26.847703
37	add-bucket-name-length-trigger	3944135b4e3e8b22d6d4cbb568fe3b0b51df15c1	2026-04-27 01:04:26.850199
38	iceberg-catalog-flag-on-buckets	02716b81ceec9705aed84aa1501657095b32e5c5	2026-04-27 01:04:26.853361
39	add-search-v2-sort-support	6706c5f2928846abee18461279799ad12b279b78	2026-04-27 01:04:26.867257
40	fix-prefix-race-conditions-optimized	7ad69982ae2d372b21f48fc4829ae9752c518f6b	2026-04-27 01:04:26.869474
41	add-object-level-update-trigger	07fcf1a22165849b7a029deed059ffcde08d1ae0	2026-04-27 01:04:26.873212
42	rollback-prefix-triggers	771479077764adc09e2ea2043eb627503c034cd4	2026-04-27 01:04:26.875734
43	fix-object-level	84b35d6caca9d937478ad8a797491f38b8c2979f	2026-04-27 01:04:26.877801
44	vector-bucket-type	99c20c0ffd52bb1ff1f32fb992f3b351e3ef8fb3	2026-04-27 01:04:26.879934
45	vector-buckets	049e27196d77a7cb76497a85afae669d8b230953	2026-04-27 01:04:26.883558
46	buckets-objects-grants	fedeb96d60fefd8e02ab3ded9fbde05632f84aed	2026-04-27 01:04:26.89418
47	iceberg-table-metadata	649df56855c24d8b36dd4cc1aeb8251aa9ad42c2	2026-04-27 01:04:26.897734
48	iceberg-catalog-ids	e0e8b460c609b9999ccd0df9ad14294613eed939	2026-04-27 01:04:26.902518
49	buckets-objects-grants-postgres	072b1195d0d5a2f888af6b2302a1938dd94b8b3d	2026-04-27 01:04:26.920732
50	search-v2-optimised	6323ac4f850aa14e7387eb32102869578b5bd478	2026-04-27 01:04:26.927206
51	index-backward-compatible-search	2ee395d433f76e38bcd3856debaf6e0e5b674011	2026-04-27 01:04:27.881124
52	drop-not-used-indexes-and-functions	5cc44c8696749ac11dd0dc37f2a3802075f3a171	2026-04-27 01:04:27.884631
53	drop-index-lower-name	d0cb18777d9e2a98ebe0bc5cc7a42e57ebe41854	2026-04-27 01:04:27.896549
54	drop-index-object-level	6289e048b1472da17c31a7eba1ded625a6457e67	2026-04-27 01:04:27.898765
55	prevent-direct-deletes	262a4798d5e0f2e7c8970232e03ce8be695d5819	2026-04-27 01:04:27.900377
57	s3-multipart-uploads-metadata	f127886e00d1b374fadbc7c6b31e09336aad5287	2026-04-27 01:04:27.909167
58	operation-ergonomics	00ca5d483b3fe0d522133d9002ccc5df98365120	2026-04-27 01:04:27.911971
56	fix-optimized-search-function	b823ed1e418101032fa01374edc9a436e54e3ed4	2026-04-27 01:04:27.90494
59	drop-unused-functions	38456f13e39691c2bbb4b5151d0d1cdbabd4a8c4	2026-05-22 21:18:09.460603
60	optimize-existing-functions-again	db35e1c91a9201e59f4fef8d972c2f277d68b157	2026-05-22 21:18:09.470763
\.


--
-- Data for Name: objects; Type: TABLE DATA; Schema: storage; Owner: supabase_storage_admin
--

COPY "storage"."objects" ("id", "bucket_id", "name", "owner", "created_at", "updated_at", "last_accessed_at", "metadata", "version", "owner_id", "user_metadata") FROM stdin;
\.


--
-- Data for Name: s3_multipart_uploads; Type: TABLE DATA; Schema: storage; Owner: supabase_storage_admin
--

COPY "storage"."s3_multipart_uploads" ("id", "in_progress_size", "upload_signature", "bucket_id", "key", "version", "owner_id", "created_at", "user_metadata", "metadata") FROM stdin;
\.


--
-- Data for Name: s3_multipart_uploads_parts; Type: TABLE DATA; Schema: storage; Owner: supabase_storage_admin
--

COPY "storage"."s3_multipart_uploads_parts" ("id", "upload_id", "size", "part_number", "bucket_id", "key", "etag", "owner_id", "version", "created_at") FROM stdin;
\.


--
-- Data for Name: vector_indexes; Type: TABLE DATA; Schema: storage; Owner: supabase_storage_admin
--

COPY "storage"."vector_indexes" ("id", "name", "bucket_id", "data_type", "dimension", "distance_metric", "metadata_configuration", "created_at", "updated_at") FROM stdin;
\.


--
-- Data for Name: secrets; Type: TABLE DATA; Schema: vault; Owner: supabase_admin
--

COPY "vault"."secrets" ("id", "name", "description", "secret", "key_id", "nonce", "created_at", "updated_at") FROM stdin;
\.


--
-- Name: refresh_tokens_id_seq; Type: SEQUENCE SET; Schema: auth; Owner: supabase_auth_admin
--

SELECT pg_catalog.setval('"auth"."refresh_tokens_id_seq"', 4, true);


--
-- Name: subscription_id_seq; Type: SEQUENCE SET; Schema: realtime; Owner: supabase_admin
--

SELECT pg_catalog.setval('"realtime"."subscription_id_seq"', 1, false);


--
-- PostgreSQL database dump complete
--


