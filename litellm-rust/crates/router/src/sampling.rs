use std::sync::LazyLock;

use fancy_regex::Regex;
use litellm_auth_aws::bedrock_model_id_and_region;
use litellm_core_utils::get_llm_provider_logic::{CustomLlmProvider, get_custom_llm_provider};
use litellm_model_catalog::Catalog;
use litellm_router_types::LitellmParams;

static BEDROCK_VERSION_SUFFIX: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"-v\d+(?::\d+)?$").expect("valid regex"));
static INFERENCE_PROFILE_MINOR: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r":\d+$").expect("valid regex"));
static DATED_RELEASE_SUFFIX: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"-\d{8}$").expect("valid regex"));
static DOTTED_VERSION: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(\d)\.(\d)").expect("valid regex"));
static THROUGHPUT_SUFFIX: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(:\d+):\d+k$").expect("valid regex"));
static CONTEXT_WINDOW_SUFFIX: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\[\w+\]$").expect("valid regex"));

const NAMES_WITHOUT_SAMPLING: [&str; 9] = [
    "fable", "opus-4-7", "opus_4_7", "opus-4.7", "opus_4.7", "opus-4-8", "opus_4_8", "opus-4.8",
    "opus_4.8",
];

fn bedrock_base_model(model_id: &str) -> String {
    let named = if model_id.starts_with("arn:") {
        model_id.rsplit('/').next().unwrap_or(model_id)
    } else {
        model_id
    };
    let without_throughput = THROUGHPUT_SUFFIX.replace(named, "$1");
    CONTEXT_WINDOW_SUFFIX
        .replace(&without_throughput, "")
        .into_owned()
}

fn bedrock_map_keys(resolved: &CustomLlmProvider<'_>) -> Vec<String> {
    let on_mantle =
        resolved.custom_llm_provider == "bedrock_mantle" || resolved.model.starts_with("mantle/");
    if !on_mantle && resolved.custom_llm_provider != "bedrock" {
        return Vec::new();
    }
    let routed = ["mantle/", "invoke/"]
        .into_iter()
        .find_map(|route| resolved.model.strip_prefix(route))
        .unwrap_or(resolved.model);
    let base = bedrock_base_model(&bedrock_model_id_and_region(routed).0);
    on_mantle
        .then(|| format!("bedrock_mantle/{base}"))
        .into_iter()
        .chain(std::iter::once(base))
        .collect()
}

fn normalized_keys(key: &str) -> [String; 6] {
    let dotted = DOTTED_VERSION.replace_all(key, "$1-$2");
    let bedrock_base = DATED_RELEASE_SUFFIX
        .replace(&BEDROCK_VERSION_SUFFIX.replace(&dotted, ""), "")
        .into_owned();
    [
        BEDROCK_VERSION_SUFFIX.replace(key, "").into_owned(),
        INFERENCE_PROFILE_MINOR.replace(key, "").into_owned(),
        DATED_RELEASE_SUFFIX.replace(key, "").into_owned(),
        dotted.into_owned(),
        bedrock_base,
        key.rfind('@')
            .filter(|at| *at > 0)
            .map_or(key, |at| &key[..at])
            .to_owned(),
    ]
}

fn map_keys(params: &LitellmParams) -> Vec<String> {
    let resolved = get_custom_llm_provider(&params.model, params.custom_llm_provider.as_deref());
    let primary: Vec<String> = std::iter::once(params.model.clone())
        .chain(resolved.as_ref().map(|resolved| resolved.model.to_owned()))
        .chain(resolved.as_ref().map(bedrock_map_keys).unwrap_or_default())
        .collect();
    let normalized = primary.iter().flat_map(|key| normalized_keys(key));
    primary.iter().cloned().chain(normalized).collect()
}

pub(crate) fn supports_sampling_params(catalog: &Catalog, params: &LitellmParams) -> bool {
    map_keys(params)
        .iter()
        .find_map(|key| {
            catalog
                .lookup(key)?
                .entry
                .model()?
                .capabilities
                .get("supports_sampling_params")
                .copied()
        })
        .unwrap_or_else(|| {
            let model = params.model.to_lowercase();
            !NAMES_WITHOUT_SAMPLING
                .iter()
                .any(|name| model.contains(name))
        })
}
