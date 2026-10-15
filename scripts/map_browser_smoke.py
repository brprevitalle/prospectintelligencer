"""Optional Chromium acceptance test; requires playwright and its Chromium browser."""
from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
    page=browser.new_page(viewport={'width':1440,'height':960})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8000')
    page.wait_for_function("window.intelligenceMap && intelligenceMap.getLayer('parcel-lines')",timeout=60000)
    page.wait_for_timeout(2500)
    page.screenshot(path='/tmp/prospect-map-statewide.jpg',type='jpeg',quality=35)
    page.locator('#hudson-view').click()
    page.wait_for_selector('#results .record',timeout=30000)
    page.locator('#results .record').first.click()
    page.wait_for_selector('.assessment-card',timeout=30000)
    page.wait_for_function("intelligenceMap.queryRenderedFeatures({layers:['parcel-fill']}).length>0",timeout=30000)
    assert 'Hudson' in page.locator('.detail-town').inner_text()
    page.get_by_role('button',name='Find nearby parcel candidates').click()
    page.wait_for_selector('.neighbors-list',timeout=30000)
    page.locator('#close-detail').click()
    page.select_option('#segment','single_family')
    page.wait_for_function("document.querySelector('#results-title').textContent==='Property records'")
    assert 'single family' in page.locator('#results .record').first.inner_text()
    page.fill('#search','MAIN')
    page.get_by_role('button',name='Search properties',exact=True).click()
    page.wait_for_function("document.querySelector('#results-title').textContent==='Search results'")
    assert page.locator('#results .record').count()>0
    page.locator('#results .record').first.click()
    page.wait_for_selector('.assessment-card',timeout=30000)
    page.wait_for_timeout(1500)
    page.screenshot(path='/tmp/prospect-map-property.jpg',type='jpeg',quality=40)
    page.locator('#layers-button').click()
    page.locator('#base-toggle').uncheck()
    assert page.evaluate("intelligenceMap.getLayoutProperty('base','visibility')")=='none'
    page.locator('#base-toggle').check()
    page.set_viewport_size({'width':390,'height':844})
    page.wait_for_timeout(1000)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert page.locator('#map').bounding_box()['height']>200
    page.screenshot(path='/tmp/prospect-map-mobile.jpg',type='jpeg',quality=40)
    print(json.dumps({'javascript_errors':errors,'coverage':page.locator('#coverage-badge').inner_text(),
                     'tests':['statewide overview','Hudson navigation','local vector tiles','parcel details','neighbors',
                              'property filter','owner/address search','layer toggle','mobile layout']}))
    assert not errors
    browser.close()
