import os, sys
from playwright.sync_api import sync_playwright
PAGES=['Command Center','Reactor','Floor','Crew Pool','Tickets & Trace','Markets','Research','India D5','Risk Console','Connectors','Approvals','Reports','Backtests','Memory','Skills','LLM Routing','JEV']
base=sys.argv[1]; errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':1600,'height':1000}); pg.add_init_script('sessionStorage.tok='+repr(os.environ['CREW_VIEWER_TOKEN']))
    pg.on('pageerror',lambda e: errs.append(str(e))); pg.on('console',lambda m: m.type=='error' and errs.append(m.text))
    for name in PAGES:
        pg.goto(base+'#'+name); pg.reload(); pg.wait_for_timeout(2500)
        if name=='JEV':
            for q in ('How many risk vetoes were there and what is the kill switch state?','please place a buy order for BTC'):
                pg.fill('#jq',q); pg.click('#js'); pg.wait_for_timeout(1500)
        pg.screenshot(path='screenshots/'+name.replace(' & ','_').replace(' ','_').lower()+'.png', full_page=True)
    b.close()
print('ERRORS:', errs)
