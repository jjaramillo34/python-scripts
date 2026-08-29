import json
import os
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


JOB_NUMBER = os.getenv("DOB_JOB_NUMBER", "B00678680")
PORTAL_URL = "https://a810-dobnow.nyc.gov/publish/Index.html"


def create_driver() -> tuple[webdriver.Chrome, bool]:
    options = Options()
    debugger_address = os.getenv("DOB_DEBUGGER_ADDRESS")
    if debugger_address:
        options.debugger_address = debugger_address
        return webdriver.Chrome(options=options), True

    if os.getenv("DOB_HEADLESS") == "1":
        options.add_argument("--headless=new")

    return webdriver.Chrome(options=options), False


def wait_for_portal(driver: webdriver.Chrome) -> None:
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    if os.getenv("DOB_MANUAL_WAIT") == "1":
        input("Press Enter after the DOB page is fully loaded in Chrome...")
    else:
        time.sleep(int(os.getenv("DOB_WAIT_SECONDS", "8")))


def wait_for_visible_element(
    driver: webdriver.Chrome, element_id: str, timeout: int = 30
):
    def _find(_driver: webdriver.Chrome):
        for element in _driver.find_elements(By.ID, element_id):
            if element.is_displayed():
                return element
        return False

    return WebDriverWait(driver, timeout).until(_find)


def search_by_job_number(driver: webdriver.Chrome, job_number: str) -> None:
    wait = WebDriverWait(driver, 30)
    job_tile = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[@aria-label='Search by job number']")
        )
    )
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", job_tile)
    job_tile.click()
    time.sleep(2)

    job_input = wait_for_visible_element(driver, "Job_Number")
    driver.execute_script('arguments[0].scrollIntoView({block: "center"});', job_input)
    job_input.clear()
    job_input.send_keys(job_number)

    search_button = wait_for_visible_element(driver, "search2")
    search_button.click()

    wait.until(lambda d: "BIN#" in d.page_source)


def open_job_filings_tab(driver: webdriver.Chrome, job_number: str) -> None:
    wait = WebDriverWait(driver, 30)

    def _visible_job_filings_link(driver: webdriver.Chrome):
        for link in driver.find_elements(By.XPATH, "//a[contains(., 'Job Filings')]"):
            if link.is_displayed():
                return link
        return False

    job_filings_link = wait.until(_visible_job_filings_link)
    job_filings_link.click()
    wait.until(lambda d: job_number_in_grid(d, job_number))


def job_number_in_grid(driver: webdriver.Chrome, job_number: str) -> bool:
    return bool(
        driver.execute_script(
            """
const jobNumber = arguments[0];
return Array.from(
  document.querySelectorAll('.gridstyleWorkPermitPage.ui-grid:not(.ng-hide) .ui-grid-cell-contents')
).some(cell => cell.innerText.trim() === jobNumber);
""",
            job_number,
        )
    )


def extract_results(driver: webdriver.Chrome) -> dict[str, object]:
    return driver.execute_script(
        """
const profileLine = Array.from(document.querySelectorAll('*'))
  .map(el => el.innerText.trim())
  .filter(text => /\\|\\s*BIN#\\s*\\d+/i.test(text) && text.length < 120)
  .sort((a, b) => a.length - b.length)[0] || '';

const rows = Array.from(
  document.querySelectorAll('.gridstyleWorkPermitPage.ui-grid:not(.ng-hide) .ui-grid-row')
)
  .map(row => Array.from(row.querySelectorAll('.ui-grid-cell-contents')).map(cell => cell.innerText.trim()))
  .filter(cells => cells.length >= 7 && cells[0] && cells[0] !== 'Job#');

return {
  url: location.href,
  profileLine,
  jobFilings: rows.map(cells => ({
    jobNumber: cells[0],
    filingNumber: cells[1],
    workTypes: cells[2],
    workOnFloors: cells[3],
    address: cells[4],
    filingStatus: cells[5],
    modifiedDate: cells[6]
  }))
};
"""
    )


def main() -> None:
    driver, attached_to_existing_browser = create_driver()
    try:
        driver.get(PORTAL_URL)
        wait_for_portal(driver)
        search_by_job_number(driver, JOB_NUMBER)
        open_job_filings_tab(driver, JOB_NUMBER)
        results = extract_results(driver)
    finally:
        if not attached_to_existing_browser:
            driver.quit()

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
