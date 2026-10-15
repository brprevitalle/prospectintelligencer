"""Optional browser smoke: pip install playwright==1.56.0 and install Chromium first."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8000/hudson')
    page.wait_for_selector('#rows tr')
    assert page.locator('#rows tr').count()==50
    assert '7,452' in page.locator('#count').inner_text()
    page.locator('#next').click()
    page.wait_for_function("!document.getElementById('prev').disabled")
    page.locator('#segment').select_option('single_family')
    page.get_by_role('button',name='Search',exact=True).click()
    page.wait_for_function("document.getElementById('prev').disabled")
    assert 'single family' in page.locator('#rows tr').first.inner_text()
    page.locator('#rows button').first.click()
    page.wait_for_selector('#detail',state='visible')
    assert 'OWNER1' in page.locator('#evidence').inner_text()
    page.locator('#segment').select_option('')
    page.locator('#issue').select_option('invalid_geometry_quarantined')
    page.get_by_role('button',name='Search',exact=True).click()
    page.wait_for_function("document.querySelectorAll('#rows tr').length===1")
    assert 'invalid geometry quarantined' in page.locator('#rows').inner_text()
    page.locator('#issue').select_option('')
    page.get_by_role('button',name='Search',exact=True).click()
    page.wait_for_function("document.querySelectorAll('#rows tr').length===50")
    page.locator('#detail').evaluate('(el)=>el.hidden=true')
    page.screenshot(path='/tmp/prospect-intelligence-desktop.png',full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    assert not errors,errors
    browser.close()
    print('Browser smoke passed: publication, pagination, segment filtering, source detail, quarantine filtering, mobile width, no JS errors.')
