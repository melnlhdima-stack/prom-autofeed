#!/usr/bin/env python3
"""Build a Prom-compatible YML feed from a supplier YML/XML file.
Run: python build_prom_feed.py INPUT.xml OUTPUT.xml
Or set SUPPLIER_FEED_URL and run without INPUT (requires requests).
Schedule every 4 hours via cron; publish OUTPUT.xml on HTTPS hosting.
"""
import os,sys,re,math,html,urllib.request
from lxml import etree
from pathlib import Path
from collections import Counter

TIERS=[(100,1.00),(250,.80),(500,.60),(750,.50),(1000,.37),(1500,.32),(2000,.29),(4000,.25),(6000,.20),(10000,.18)]
OVER_10000=float(os.environ.get('OVER_10000_MARKUP','15'))/100
ROUNDING=os.environ.get('PRICE_ROUNDING','integer')
UA_MAP={'Квадрокоптеры':'Квадрокоптери','Машинки на радиоуправлении':'Радіокеровані машинки','Дроны для начинающих':'Дрони для початківців','Дроны с GPS и автовозвратом':'Дрони з GPS та автоповерненням','Дроны с 3-осевым подвесом':'Дрони з 3-осьовим підвісом','Дрифт машинки':'Дрифт-машинки','Внедорожники':'Позашляховики','Радиоуправляемый мотоцикл':'Радіокерований мотоцикл','Машинки с камерой':'Машинки з камерою'}
RU_MAP={'Квадрокоптери':'Квадрокоптеры','Радіокеровані машинки':'Машинки на радиоуправлении'}

def clean(s): return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',s or ''))).strip()
def price_markup(p):
    rate=next((r for lim,r in TIERS if p<=lim),OVER_10000)
    v=p*(1+rate)
    if ROUNDING=='nine': return math.ceil((v-9)/10)*10+9
    if ROUNDING=='99': return math.ceil((v-99)/100)*100+99
    return math.ceil(v)

def seo_name(original,category,lang):
    s=clean(original).strip(' ,.-')
    # Retain supplier model, brand, package and numerical specs; remove redundant sales adjectives.
    s=re.sub(r'\b(профессиональный|професійний|крутой|крутий|новинка|лучший|найкращий)\b','',s,flags=re.I)
    s=re.sub(r'\s+',' ',s).strip(' ,.-')
    if not s: s=category
    # Put a high-intent product type first if the supplier title starts with generic marketing words.
    if re.search(r'квадрокоптер|дрон|коптер',s,re.I):
        if not re.match(r'(?i)^(квадрокоптер|дрон|коптер|радіокерований квадрокоптер|радиоуправляемый квадрокоптер)',s):
            s=('Квадрокоптер ' if lang=='ua' else 'Квадрокоптер ')+s
    return s[:250].rstrip(' ,.-')

def key_terms(name,category,lang):
    terms=[]
    name=clean(name)
    terms.append(name[:100]); terms.append(category)
    # Only add relevant intent phrases grounded in title/category.
    if re.search('квадрокоптер|дрон|коптер',name,re.I):
        terms+=(['купити квадрокоптер','дрон з камерою'] if lang=='ua' else ['купить квадрокоптер','дрон с камерой']) if re.search('камер',name,re.I) else (['купити квадрокоптер','радіокерований дрон'] if lang=='ua' else ['купить квадрокоптер','радиоуправляемый дрон'])
    if re.search('машин|автомоб|краулер|баггі|багги|трак',name,re.I): terms+=(['радіокерована машинка','машинка на пульті'] if lang=='ua' else ['радиоуправляемая машинка','машинка на пульте'])
    for pattern in (r'\b[A-Z][A-Za-z0-9-]{2,}\b',r'\b[A-ZА-ЯІЇЄҐ]{1,5}[- ]?\d[A-Za-zА-Яа-я0-9-]*\b'):
        for m in re.findall(pattern,name): terms.append((category+' '+m).strip())
    return ', '.join(dict.fromkeys(x for x in terms if x))[:1000]

def desc(title,raw,params,lang):
    source=clean(raw)
    # Keep original technical information intact: no invented specifications.
    # Add a concise unique product-focused introduction and section structure.
    lead=(f'{title}. Ознайомтеся з характеристиками та комплектацією моделі перед замовленням.' if lang=='ua' else f'{title}. Ознакомьтесь с характеристиками и комплектацией модели перед заказом.')
    section=('Опис і особливості' if lang=='ua' else 'Описание и особенности')
    char=('Основні характеристики' if lang=='ua' else 'Основные характеристики')
    # Preserve supplied source description, which may contain important caveats.
    blocks=[f'<h2>{html.escape(title)}</h2>',f'<p>{html.escape(lead)}</p>',f'<h3>{section}</h3>',f'<p>{html.escape(source)}</p>']
    if params:
        blocks.append(f'<h3>{char}</h3><ul>')
        for k,v in params: blocks.append(f'<li><strong>{html.escape(k)}:</strong> {html.escape(v)}</li>')
        blocks.append('</ul>')
    return ''.join(blocks)

def build(source,target):
    parser=etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True,recover=False)
    tree=etree.parse(str(source),parser)
    cats={c.get('id'):clean(c.text) for c in tree.findall('.//categories/category')}
    for c in tree.findall('.//categories/category'):
        if c.text in UA_MAP: c.text=UA_MAP[c.text]
    counts=Counter()
    for offer in tree.findall('.//offers/offer'):
        p=offer.find('price')
        if p is None or not p.text: counts['missing_price']+=1;continue
        try: cost=float(p.text.replace(',','.'))
        except ValueError: counts['invalid_price']+=1;continue
        p.text=str(price_markup(cost)); counts['processed']+=1
        if cost>10000: counts['over_10000']+=1
        cat=cats.get(offer.findtext('categoryId'),'')
        n_ua=offer.find('name_ua'); n_ru=offer.find('name')
        ua=seo_name(n_ua.text if n_ua is not None and n_ua.text else (n_ru.text if n_ru is not None else ''),UA_MAP.get(cat,cat),'ua')
        ru=seo_name(n_ru.text if n_ru is not None else ua,RU_MAP.get(cat,cat),'ru')
        if n_ua is None: n_ua=etree.SubElement(offer,'name_ua')
        if n_ru is None: n_ru=etree.SubElement(offer,'name')
        n_ua.text=ua;n_ru.text=ru
        params=[(x.get('name','Характеристика')+((' ('+x.get('unit')+')') if x.get('unit') else ''),clean(x.text)) for x in offer.findall('param') if clean(x.text)]
        for tag,title,language in [('description_ua',ua,'ua'),('description',ru,'ru')]:
            el=offer.find(tag)
            if el is None: el=etree.SubElement(offer,tag)
            original=el.text or ''
            el.text=etree.CDATA(desc(title,original,params,language))
        for tag,title,language in [('keywords_ua',ua,'ua'),('keywords',ru,'ru')]:
            el=offer.find(tag)
            if el is None: el=etree.SubElement(offer,tag)
            el.text=key_terms(title,UA_MAP.get(cat,cat) if language=='ua' else cat,language)
        # Old supplier price is not a valid promotional price after repricing.
        old=offer.find('oldprice')
        if old is not None: offer.remove(old)
        counts['available' if offer.get('available')=='true' else 'unavailable']+=1
    tree.getroot().set('date',__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'))
    tree.write(str(target),encoding='utf-8',xml_declaration=True,pretty_print=True,doctype='<!DOCTYPE yml_catalog SYSTEM "shops.dtd">')
    return counts

if __name__=='__main__':
    source=sys.argv[1] if len(sys.argv)>1 else None
    target=sys.argv[2] if len(sys.argv)>2 else '/var/www/html/prom.xml'
    if not source:
        url=os.environ['SUPPLIER_FEED_URL'];source='/tmp/supplier_prom.xml'
        with urllib.request.urlopen(url,timeout=120) as resp,open(source,'wb') as f:
            import shutil;shutil.copyfileobj(resp,f)
    print(dict(build(source,target)))
