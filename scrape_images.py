from duckduckgo_search import DDGS

results = DDGS().images(
    keywords="butterfly",
    region="wt-wt",
    safesearch="off",
    size=None,
    color="Monochrome",
    type_image=None,
    layout=None,
    license_image=None,
    max_results=10,
)
print(results)