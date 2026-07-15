const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');

const OUTDIR = __dirname;
const market = JSON.parse(fs.readFileSync(path.join(OUTDIR, 'market_pack.json'), 'utf8'));
const news = JSON.parse(fs.readFileSync(path.join(OUTDIR, 'news_pack.json'), 'utf8'));
const editorial = JSON.parse(fs.readFileSync(path.join(OUTDIR, 'editorial_memo.json'), 'utf8'));

const pptx = new pptxgen();
pptx.defineLayout({ name: 'A4P', width: 8.267, height: 11.693 });
pptx.layout = 'A4P';
pptx.author = 'OpenAI';
pptx.subject = 'NOWHERE NOON BRIEF demo';
pptx.title = 'NOWHERE NOON BRIEF - 2026-07-14 14:30 KST';
pptx.company = 'Internal Demo';
pptx.lang = 'ko-KR';
pptx.theme = {
  headFontFace: 'NanumSquare',
  bodyFontFace: 'Noto Sans CJK KR',
  lang: 'ko-KR'
};
pptx.defineSlideMaster({
  title: 'MASTER',
  background: { color: 'F4F6F8' },
  objects: [
    { rect: { x: 0, y: 0, w: 8.267, h: 0.12, fill: { color: '0B1F33' }, line: { color: '0B1F33' } } },
    { text: { text: 'NOWHERE / NOON BRIEF', options: { x: 0.42, y: 0.22, w: 3.6, h: 0.22, fontFace: 'NanumSquare', fontSize: 8.5, bold: true, color: '0B1F33', margin: 0 } } },
    { text: { text: 'DEMO · INTERNAL USE', options: { x: 5.93, y: 0.22, w: 1.92, h: 0.22, fontFace: 'NanumSquare', fontSize: 7.5, bold: true, color: '647586', align: 'right', margin: 0 } } },
    { line: { x: 0.42, y: 11.20, w: 7.42, h: 0, line: { color: 'D8DEE5', width: 0.8 } } },
  ],
  slideNumber: { x: 7.47, y: 11.28, color: '647586', fontFace: 'NanumSquare', fontSize: 8 }
});

const C = {
  navy: '0B1F33',
  slate: '263A4D',
  muted: '647586',
  border: 'D8DEE5',
  paper: 'F4F6F8',
  white: 'FFFFFF',
  teal: '00A6A6',
  tealLite: 'DFF4F2',
  red: 'D9534F',
  redLite: 'FBE7E5',
  blue: '3B73B9',
  blueLite: 'E5EDF8',
  gold: 'D8A63C',
  goldLite: 'F7EED8',
  ink: '17212B',
  grayLite: 'E9EDF1',
  darkGray: '465866'
};

function addText(slide, text, x, y, w, h, opts={}) {
  const options = {
    x,y,w,h,
    fontFace: opts.fontFace || 'Noto Sans CJK KR',
    fontSize: opts.fontSize || 10,
    color: opts.color || C.ink,
    bold: opts.bold || false,
    margin: opts.margin !== undefined ? opts.margin : 0,
    valign: opts.valign || 'mid',
    align: opts.align || 'left',
    breakLine: false,
    fit: 'shrink',
    ...opts
  };
  slide.addText(text, options);
}

function addCard(slide, x, y, w, h, opts={}) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,y,w,h,
    rectRadius: 0.08,
    fill: { color: opts.fill || C.white, transparency: opts.transparency || 0 },
    line: { color: opts.line || C.border, width: opts.lineWidth || 0.8 },
    shadow: opts.shadow === false ? undefined : { type: 'outer', color: '9DAAB5', blur: 1.5, angle: 45, distance: 0.5, opacity: 0.10 }
  });
}

function addSectionTitle(slide, label, title, subtitle='') {
  addText(slide, label.toUpperCase(), 0.42, 0.56, 1.45, 0.18, { fontFace:'NanumSquare', fontSize:7.5, bold:true, color:C.teal, charSpacing:1.1 });
  addText(slide, title, 0.42, 0.78, 7.25, 0.46, { fontFace:'NanumSquare', fontSize:22, bold:true, color:C.navy, valign:'top' });
  if (subtitle) addText(slide, subtitle, 0.42, 1.23, 7.25, 0.40, { fontSize:9.4, color:C.darkGray, valign:'top', breakLine:true });
}

function addFooter(slide, sourceText, asOf='') {
  addText(slide, sourceText, 0.42, 11.24, 6.55, 0.20, { fontSize:6.5, color:C.muted, valign:'top' });
  if (asOf) addText(slide, asOf, 6.25, 10.98, 1.58, 0.18, { fontFace:'NanumSquare', fontSize:6.8, bold:true, color:C.muted, align:'right' });
}

function fmtPct(v, digits=2) { return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`; }
function fmtNum(v, digits=2) { return v.toLocaleString('ko-KR', {minimumFractionDigits:digits, maximumFractionDigits:digits}); }
function fmtFlow(v) { return `${v >= 0 ? '+' : ''}${Math.round(v).toLocaleString('ko-KR')}억`; }
function upColor(v) { return v >= 0 ? C.red : C.blue; }
function liteColor(v) { return v >= 0 ? C.redLite : C.blueLite; }

function addRangeBar(slide, item, x, y, w, labelColor) {
  addCard(slide, x, y, w, 1.34, { shadow:false });
  addText(slide, item.name, x+0.16, y+0.13, 1.2, 0.25, { fontFace:'NanumSquare', fontSize:11, bold:true, color:C.navy });
  addText(slide, fmtNum(item.last,2), x+1.1, y+0.11, 1.7, 0.30, { fontFace:'NanumSquare', fontSize:15, bold:true, color:C.navy, align:'right' });
  addText(slide, fmtPct(item.change_pct,2), x+2.84, y+0.13, 0.92, 0.25, { fontFace:'NanumSquare', fontSize:10.5, bold:true, color:upColor(item.change_pct), align:'right' });
  const barX=x+0.25, barY=y+0.72, barW=w-0.50;
  slide.addShape(pptx.ShapeType.line, { x:barX, y:barY, w:barW, h:0, line:{color:'C8D0D8', width:3, beginArrowType:'none', endArrowType:'none'} });
  const pos = Math.max(0, Math.min(1, item.position_in_range_pct/100));
  const openPos = (item.open-item.low)/(item.high-item.low);
  const prevPos = (item.prev_close-item.low)/(item.high-item.low);
  slide.addShape(pptx.ShapeType.line, { x:barX+barW*prevPos, y:barY-0.12, w:0, h:0.24, line:{color:C.gold, width:1.4} });
  slide.addShape(pptx.ShapeType.line, { x:barX+barW*openPos, y:barY-0.10, w:0, h:0.20, line:{color:C.darkGray, width:1.2} });
  slide.addShape(pptx.ShapeType.ellipse, { x:barX+barW*pos-0.055, y:barY-0.055, w:0.11, h:0.11, fill:{color:labelColor}, line:{color:C.white, width:0.8} });
  addText(slide, `저 ${fmtNum(item.low,0)}`, barX, y+0.85, 0.9, 0.20, {fontSize:6.7,color:C.muted});
  addText(slide, `전일 ${fmtNum(item.prev_close,0)}`, barX+barW*prevPos-0.35, y+0.92, 0.7, 0.20, {fontSize:6.5,color:C.gold,align:'center'});
  addText(slide, `시가 ${fmtNum(item.open,0)}`, barX+barW*openPos-0.32, y+0.47, 0.64, 0.20, {fontSize:6.5,color:C.darkGray,align:'center'});
  addText(slide, `고 ${fmtNum(item.high,0)}`, barX+barW-0.9, y+0.85, 0.9, 0.20, {fontSize:6.7,color:C.muted,align:'right'});
  addText(slide, `저점 대비 ${fmtPct(item.recovery_from_low_pct,1)}`, x+0.18, y+1.06, w-0.36, 0.19, {fontFace:'NanumSquare',fontSize:7.5,bold:true,color:labelColor,align:'right'});
}

function addBreadth(slide, b, x, y, w, h) {
  addCard(slide,x,y,w,h,{shadow:false});
  addText(slide,b.market,x+0.15,y+0.10,0.75,0.22,{fontFace:'NanumSquare',fontSize:9.5,bold:true,color:C.navy});
  addText(slide,`상승 ${b.advancers} · 보합 ${b.unchanged} · 하락 ${b.decliners}`,x+0.95,y+0.10,w-1.1,0.22,{fontSize:7.4,color:C.muted,align:'right'});
  const total=b.advancers+b.unchanged+b.decliners;
  const bx=x+0.18, by=y+0.50, bw=w-0.36, bh=0.18;
  const a=b.advancers/total, u=b.unchanged/total, d=b.decliners/total;
  slide.addShape(pptx.ShapeType.rect,{x:bx,y:by,w:bw*a,h:bh,fill:{color:C.red},line:{color:C.red}});
  slide.addShape(pptx.ShapeType.rect,{x:bx+bw*a,y:by,w:bw*u,h:bh,fill:{color:'C5CCD3'},line:{color:'C5CCD3'}});
  slide.addShape(pptx.ShapeType.rect,{x:bx+bw*(a+u),y:by,w:bw*d,h:bh,fill:{color:C.blue},line:{color:C.blue}});
  addText(slide,`상승 비율 ${b.advancer_ratio_ex_flat_pct.toFixed(1)}%`,x+0.18,y+0.76,w-0.36,0.22,{fontFace:'NanumSquare',fontSize:9,bold:true,color:b.advancer_ratio_ex_flat_pct<35?C.blue:C.navy});
}

function addMetricCard(slide, x,y,w,h,label,value,change,note,color=C.navy) {
  addCard(slide,x,y,w,h,{shadow:false});
  addText(slide,label,x+0.14,y+0.10,w-0.28,0.18,{fontFace:'NanumSquare',fontSize:7.5,bold:true,color:C.muted});
  addText(slide,value,x+0.14,y+0.35,w-0.28,0.32,{fontFace:'NanumSquare',fontSize:17,bold:true,color:C.navy});
  if(change) addText(slide,change,x+0.14,y+0.72,w-0.28,0.22,{fontFace:'NanumSquare',fontSize:9,bold:true,color:color});
  if(note) addText(slide,note,x+0.14,y+h-0.34,w-0.28,0.24,{fontSize:6.5,color:C.muted,valign:'top'});
}

function addBullet(slide, text, x, y, w, opts={}) {
  slide.addShape(pptx.ShapeType.ellipse,{x:x,y:y+0.065,w:0.055,h:0.055,fill:{color:opts.color||C.teal},line:{color:opts.color||C.teal}});
  addText(slide,text,x+0.13,y,w-0.13,opts.h||0.42,{fontSize:opts.fontSize||9.1,color:opts.textColor||C.ink,valign:'top',breakLine:true});
}

function addTag(slide, text, x,y,w,color,fill) {
  slide.addShape(pptx.ShapeType.roundRect,{x,y,w,h:0.26,rectRadius:0.06,fill:{color:fill},line:{color:fill}});
  addText(slide,text,x,y+0.01,w,0.22,{fontFace:'NanumSquare',fontSize:6.8,bold:true,color,align:'center'});
}

// Data helpers
const kospi = market.indices.find(x=>x.symbol==='KOSPI');
const kosdaq = market.indices.find(x=>x.symbol==='KOSDAQ');
const bKospi = market.breadth.find(x=>x.market==='KOSPI');
const bKosdaq = market.breadth.find(x=>x.market==='KOSDAQ');
const fx = market.fx[0];
const global = Object.fromEntries(market.global_context.map(x=>[x.symbol,x]));

// PAGE 1
{
  const s = pptx.addSlide('MASTER');
  addSectionTitle(s,'Market snapshot',editorial.title,editorial.one_liner);

  addRangeBar(s,kospi,0.42,1.72,3.62,C.red);
  addRangeBar(s,kosdaq,4.21,1.72,3.62,C.blue);

  addMetricCard(s,0.42,3.22,2.34,1.24,'USD/KRW PROXY',fmtNum(fx.value,2),fmtPct(fx.change_pct,2),'하나은행 고시환율 · 14:44',C.blue);
  addMetricCard(s,2.92,3.22,2.34,1.24,'KOSPI 상승 종목 비율',`${bKospi.advancer_ratio_ex_flat_pct.toFixed(1)}%`,'272 상승 / 608 하락','보합 제외',C.blue);
  addMetricCard(s,5.42,3.22,2.41,1.24,'KOSDAQ 상승 종목 비율',`${bKosdaq.advancer_ratio_ex_flat_pct.toFixed(1)}%`,'409 상승 / 1,254 하락','보합 제외',C.blue);

  addText(s,'오늘 시장 5문장',0.42,4.76,3.55,0.30,{fontFace:'NanumSquare',fontSize:13,bold:true,color:C.navy});
  editorial.summary_bullets.forEach((t,i)=>addBullet(s,t,0.46,5.17+i*0.76,3.47,{fontSize:8.7,h:0.60,color:i===0?C.red:C.teal}));

  addText(s,'전일 글로벌 위험 신호',4.23,4.76,3.60,0.30,{fontFace:'NanumSquare',fontSize:13,bold:true,color:C.navy});
  const cards=[
    ['S&P 500',fmtPct(global.SPX.change_pct,1),'미국 대형주',global.SPX.change_pct],
    ['NASDAQ',fmtPct(global.NASDAQ.change_pct,1),'성장주',global.NASDAQ.change_pct],
    ['SOX',fmtPct(global.SOX.change_pct,1),'반도체',global.SOX.change_pct],
    ['WTI',fmtPct(global.WTI.change_pct,1),'$78.1/bbl',global.WTI.change_pct],
    ['US 10Y',`${global.US10Y.value.toFixed(3)}%`,'+1.2bp',1],
    ['DXY',`${global.DXY.value.toFixed(2)}`,fmtPct(global.DXY.change_pct,1),global.DXY.change_pct]
  ];
  cards.forEach((c,i)=>{
    const col=i%2,row=Math.floor(i/2),x=4.23+col*1.84,y=5.18+row*1.18;
    addCard(s,x,y,1.69,0.98,{shadow:false,fill:liteColor(c[3])});
    addText(s,c[0],x+0.12,y+0.10,1.45,0.18,{fontFace:'NanumSquare',fontSize:7.5,bold:true,color:C.muted});
    addText(s,c[1],x+0.12,y+0.32,1.45,0.30,{fontFace:'NanumSquare',fontSize:15,bold:true,color:upColor(c[3])});
    addText(s,c[2],x+0.12,y+0.69,1.45,0.17,{fontSize:6.8,color:C.darkGray});
  });
  addCard(s,4.23,8.86,3.60,1.25,{fill:C.navy,line:C.navy,shadow:false});
  addText(s,'PAGE THESIS',4.43,9.03,1.20,0.18,{fontFace:'NanumSquare',fontSize:7,bold:true,color:'8FE0D8',charSpacing:1.0});
  addText(s,'반등은 지수에,\n불안은 시장 전체에.',4.43,9.30,3.05,0.58,{fontFace:'NanumSquare',fontSize:17,bold:true,color:C.white,valign:'top',breakLine:true});
  addText(s,'코스피의 강한 복원과 코스닥·시장 폭의 약세를 함께 본다.',4.43,9.87,3.00,0.20,{fontSize:7.2,color:'D3DEE8'});

  addFooter(s,'Sources: Naver Finance snapshots; Shinhan Daily Market Digest (user-provided reference). Prototype only.','시장 14:28-14:30 · FX 14:44 KST');
}

// PAGE 2
{
  const s = pptx.addSlide('MASTER');
  addSectionTitle(s,'Korea market structure','반등의 질은 좁다','지수 수준, 시장 폭, 수급, 대표 종목을 한 화면에서 비교한다.');
  addRangeBar(s,kospi,0.42,1.70,3.62,C.red);
  addRangeBar(s,kosdaq,4.21,1.70,3.62,C.blue);

  addText(s,'시장 폭',0.42,3.29,3.62,0.28,{fontFace:'NanumSquare',fontSize:12.5,bold:true,color:C.navy});
  addBreadth(s,bKospi,0.42,3.65,3.62,1.13);
  addBreadth(s,bKosdaq,0.42,4.93,3.62,1.13);

  addText(s,'투자자·프로그램 누적 순매수',4.21,3.29,3.62,0.28,{fontFace:'NanumSquare',fontSize:12.5,bold:true,color:C.navy});
  addCard(s,4.21,3.65,3.62,2.41,{shadow:false});
  const flowRows = [
    ['KOSPI 개인',-39808],['KOSPI 외국인',4838],['KOSPI 기관',35242],['KOSPI 프로그램',9127],
    ['KOSDAQ 외국인',-1772],['KOSDAQ 기관',1019],['KOSDAQ 프로그램',-1278]
  ];
  const maxAbs=40000;
  flowRows.forEach((r,i)=>{
    const y=3.84+i*0.29;
    addText(s,r[0],4.37,y,1.22,0.18,{fontSize:7.2,color:C.darkGray});
    const center=6.18, maxW=1.28, bw=Math.abs(r[1])/maxAbs*maxW;
    s.addShape(pptx.ShapeType.line,{x:center,y:y+0.09,w:0,h:0.18,line:{color:'AEB9C3',width:0.8}});
    if(r[1]>=0) s.addShape(pptx.ShapeType.rect,{x:center,y:y+0.03,w:bw,h:0.12,fill:{color:C.red},line:{color:C.red}});
    else s.addShape(pptx.ShapeType.rect,{x:center-bw,y:y+0.03,w:bw,h:0.12,fill:{color:C.blue},line:{color:C.blue}});
    addText(s,fmtFlow(r[1]),7.08,y,0.58,0.18,{fontFace:'NanumSquare',fontSize:7,bold:true,color:upColor(r[1]),align:'right'});
  });
  addText(s,'단위: 억원 · 공개 페이지 표시값',4.38,5.80,3.14,0.15,{fontSize:6.3,color:C.muted,align:'right'});

  addText(s,'시가총액 상위·핵심 종목',0.42,6.42,7.41,0.28,{fontFace:'NanumSquare',fontSize:12.5,bold:true,color:C.navy});
  const movers=market.movers.slice(0,10);
  movers.forEach((m,i)=>{
    const col=i%5,row=Math.floor(i/5),x=0.42+col*1.50,y=6.82+row*1.03;
    addCard(s,x,y,1.37,0.87,{shadow:false,fill:liteColor(m.change_pct),line:liteColor(m.change_pct)});
    addText(s,m.name,x+0.10,y+0.10,1.17,0.22,{fontFace:'NanumSquare',fontSize:7.4,bold:true,color:C.navy});
    addText(s,fmtPct(m.change_pct,2),x+0.10,y+0.40,1.17,0.28,{fontFace:'NanumSquare',fontSize:12.3,bold:true,color:upColor(m.change_pct)});
  });

  const obs=[
    ['01','코스피는 강하게 반등했지만 상승 종목보다 하락 종목이 2.2배 많다.'],
    ['02','기관·프로그램은 코스피를 지지했지만 코스닥 외국인·프로그램은 순매도다.'],
    ['03','삼성전자·SK하이닉스 강세와 바이오·2차전지 약세가 지수 간 격차를 만들었다.']
  ];
  obs.forEach((o,i)=>{
    const y=9.07+i*0.49;
    addTag(s,o[0],0.42,y,0.40,C.teal,C.tealLite);
    addText(s,o[1],0.94,y,6.84,0.35,{fontSize:8.6,color:C.ink,valign:'top'});
  });
  addFooter(s,'Sources: Naver Finance KOSPI/KOSDAQ snapshots. Flow values shown in KRW 100m units.','14:28-14:30 KST');
}

// PAGE 3
{
  const s = pptx.addSlide('MASTER');
  addSectionTitle(s,'News & catalysts','기사보다 사건을 본다','news cutoff 14:45 KST · 시장과 연결되는 사건만 남긴다.');

  addText(s,'오늘 사건 타임라인',0.42,1.72,2.20,0.28,{fontFace:'NanumSquare',fontSize:12.5,bold:true,color:C.navy});
  addCard(s,0.42,2.08,2.20,7.92,{shadow:false});
  s.addShape(pptx.ShapeType.line,{x:0.82,y:2.52,w:0,h:6.82,line:{color:'B8C3CD',width:1.5}});
  const timeline=[
    ['08:26','레버리지 ETF\n대응 회의 예고',C.gold],
    ['08:34','ASML 실적\n프리뷰',C.teal],
    ['08:56','SK하이닉스\n기대치 재조정',C.teal],
    ['12:06','코스닥 매도\n사이드카',C.blue],
    ['15:00','증권사 CEO\n긴급 회의',C.gold],
    ['21:30','미국 6월 CPI',C.red],
    ['7/15 14:00','ASML 실적',C.teal],
    ['7/16','TSMC 실적',C.teal]
  ];
  timeline.forEach((t,i)=>{
    const y=2.35+i*0.88;
    s.addShape(pptx.ShapeType.ellipse,{x:0.74,y:y+0.09,w:0.16,h:0.16,fill:{color:t[2]},line:{color:C.white,width:1}});
    addText(s,t[0],1.02,y,0.72,0.20,{fontFace:'NanumSquare',fontSize:7.2,bold:true,color:t[2]});
    addText(s,t[1],1.02,y+0.21,1.34,0.45,{fontSize:7.6,color:C.ink,valign:'top',breakLine:true});
  });

  addText(s,'핵심 뉴스 6개',2.86,1.72,4.97,0.28,{fontFace:'NanumSquare',fontSize:12.5,bold:true,color:C.navy});
  const bullets=editorial.news_bullets;
  bullets.forEach((n,i)=>{
    const y=2.08+i*1.15;
    addCard(s,2.86,y,4.97,1.00,{shadow:false,fill:i===0?C.blueLite:C.white,line:i===0?'BDD1EB':C.border});
    addTag(s,`${String(i+1).padStart(2,'0')}`,3.02,y+0.13,0.40,i===0?C.blue:C.teal,i===0?'D5E3F5':C.tealLite);
    addText(s,n.headline,3.54,y+0.10,4.07,0.34,{fontFace:'NanumSquare',fontSize:8.7,bold:true,color:C.navy,valign:'top'});
    addText(s,n.market_connection,3.54,y+0.48,4.07,0.36,{fontSize:7.3,color:C.darkGray,valign:'top',breakLine:true});
  });

  addCard(s,2.86,9.15,4.97,0.85,{fill:C.navy,line:C.navy,shadow:false});
  addText(s,'편집 원칙',3.04,9.30,0.86,0.19,{fontFace:'NanumSquare',fontSize:7.2,bold:true,color:'8FE0D8'});
  addText(s,'속보는 “원인”이 아니라 검색·검증의 출발점이다. 가격 반응과 공식 사실이 붙은 사건만 본문에 남긴다.',3.04,9.54,4.56,0.28,{fontSize:8,color:C.white,valign:'top'});

  addFooter(s,'Sources: Yonhap Infomax public articles; U.S. BLS official release calendar. Paraphrased for internal demo.','news cutoff 14:45 KST');
}

// PAGE 4
{
  const s = pptx.addSlide('MASTER');
  addSectionTitle(s,'Story 01','지수 반등인가, 반도체가 만든 지수 복원인가','질문: 코스피 플러스 전환을 시장 전체의 안정으로 읽어도 되는가?');

  addCard(s,0.42,1.73,5.18,8.62,{shadow:false});
  addTag(s,'FACT',0.64,1.96,0.72,C.teal,C.tealLite);
  addText(s,'코스피는 장중 저점 대비 7.26% 반등했고 당일 범위의 88% 지점까지 올라왔다. 하지만 상승 종목은 272개, 하락 종목은 608개다. 코스닥은 52주 저점과 매도 사이드카를 거친 뒤에도 -2.08%이며, 방향성 종목 중 상승 비율은 24.59%다.',0.64,2.35,4.72,1.45,{fontSize:10.2,color:C.ink,valign:'top',breakLine:true});
  s.addShape(pptx.ShapeType.line,{x:0.64,y:3.92,w:4.72,h:0,line:{color:C.border,width:0.8}});

  addTag(s,'INTERPRETATION',0.64,4.17,1.42,C.navy,'E6EBEF');
  addText(s,'오후 코스피 반등은 광범위한 위험선호 복귀보다 반도체 대형주, 기관, 프로그램이 만든 좁은 지수 복원으로 보는 편이 타당하다. 삼성전자와 SK하이닉스는 강하게 반등했지만 현대차·바이오·2차전지 등 다른 축은 약하다. 환율 프록시 하락은 완충 요인이지만 시장 내부의 포지션 축소가 끝났다는 증거는 아니다.',0.64,4.58,4.72,1.77,{fontSize:10.2,color:C.ink,valign:'top',breakLine:true});
  s.addShape(pptx.ShapeType.line,{x:0.64,y:6.47,w:4.72,h:0,line:{color:C.border,width:0.8}});

  addTag(s,'COUNTER / CONDITIONS',0.64,6.72,1.75,C.gold,C.goldLite);
  addText(s,'반론은 분명하다. 코스피가 전일 종가를 회복했고 장중 고점에 가까워 과매도 정상화가 이미 진행 중일 수 있다. 따라서 코스닥이 800선 부근을 되찾고 상승 종목 비율이 40% 이상으로 확대되며, 외국인 매수가 비반도체로 번지면 “좁은 기술적 반등”이라는 판단을 수정해야 한다.',0.64,7.13,4.72,1.67,{fontSize:10.2,color:C.ink,valign:'top',breakLine:true});

  addCard(s,5.82,1.73,2.01,3.08,{fill:C.navy,line:C.navy,shadow:false});
  addText(s,'근거 숫자',6.03,1.96,1.56,0.22,{fontFace:'NanumSquare',fontSize:9,bold:true,color:'8FE0D8'});
  const ev=[['KOSPI',fmtPct(kospi.change_pct,2),C.red],['저점 회복',fmtPct(kospi.recovery_from_low_pct,1),C.red],['KOSPI 상승비율',`${bKospi.advancer_ratio_ex_flat_pct.toFixed(1)}%`,C.blue],['KOSDAQ',fmtPct(kosdaq.change_pct,2),C.blue],['KOSDAQ 상승비율',`${bKosdaq.advancer_ratio_ex_flat_pct.toFixed(1)}%`,C.blue]];
  ev.forEach((e,i)=>{
    addText(s,e[0],6.03,2.36+i*0.43,0.98,0.20,{fontSize:7.3,color:'CFD9E2'});
    addText(s,e[1],7.00,2.32+i*0.43,0.58,0.24,{fontFace:'NanumSquare',fontSize:9.5,bold:true,color:e[2],align:'right'});
  });

  addCard(s,5.82,5.05,2.01,2.05,{shadow:false});
  addText(s,'판단을 바꿀 조건',6.03,5.25,1.56,0.22,{fontFace:'NanumSquare',fontSize:8.4,bold:true,color:C.navy});
  ['코스닥 800선 접근','상승비율 40%+','외국인 코스닥 매도 둔화','비반도체 대형주 안정'].forEach((t,i)=>addBullet(s,t,6.05,5.67+i*0.34,1.49,{fontSize:7.1,h:0.24,color:C.gold}));

  addCard(s,5.82,7.33,2.01,3.02,{fill:C.tealLite,line:'B8E4DF',shadow:false});
  addText(s,'진행자 질문',6.03,7.56,1.56,0.22,{fontFace:'NanumSquare',fontSize:8.4,bold:true,color:C.teal});
  addText(s,'“지수가 반등했다는 것과 시장이 안정됐다는 것은 같은 의미인가요?”',6.03,8.04,1.56,1.15,{fontFace:'NanumSquare',fontSize:13,bold:true,color:C.navy,valign:'top',breakLine:true});
  addText(s,'이어갈 질문\n- 코스닥은 왜 다르게 움직이나\n- 외국인보다 기관·프로그램의 역할이 큰가',6.03,9.25,1.56,0.76,{fontSize:7.1,color:C.darkGray,valign:'top',breakLine:true});

  addFooter(s,'Evidence: Naver Finance market snapshots; Yonhap Infomax sidecar report. Interpretation is a demo editorial judgment.','14:30 KST');
}

// PAGE 5
{
  const s = pptx.addSlide('MASTER');
  addSectionTitle(s,'Story 02','반도체 펀더멘털 훼손인가, 기대치·포지션 재조정인가','단정 대신 실적 기대, 업황 근거, 수급 증폭을 분리한다.');

  addCard(s,0.42,1.72,3.61,2.36,{fill:C.tealLite,line:'B8E4DF',shadow:false});
  addText(s,'업황 강세를 지지하는 근거',0.64,1.95,3.15,0.24,{fontFace:'NanumSquare',fontSize:11,bold:true,color:C.teal});
  addBullet(s,'TSMC 6월 매출 +67.9% YoY',0.66,2.39,3.08,{fontSize:8.5,h:0.34,color:C.teal});
  addBullet(s,'HBM 구조적 공급 제약과 LTA',0.66,2.82,3.08,{fontSize:8.5,h:0.34,color:C.teal});
  addBullet(s,'ASML 메모리 주문 강도가 다음 선행지표',0.66,3.25,3.08,{fontSize:8.5,h:0.46,color:C.teal});

  addCard(s,4.22,1.72,3.61,2.36,{fill:C.goldLite,line:'E8D7AE',shadow:false});
  addText(s,'기대치·수급 부담',4.44,1.95,3.15,0.24,{fontFace:'NanumSquare',fontSize:11,bold:true,color:'9A6C10'});
  addBullet(s,'SK하이닉스 2Q 추정치, 컨센서스 대비 -8%',4.46,2.39,3.08,{fontSize:8.5,h:0.46,color:C.gold});
  addBullet(s,'전일 SOX -4.8%, 높아진 밸류에이션 피로',4.46,2.90,3.08,{fontSize:8.5,h:0.38,color:C.gold});
  addBullet(s,'레버리지 ETF는 장 후반 변동성 증폭 가능',4.46,3.35,3.08,{fontSize:8.5,h:0.40,color:C.gold});

  addCard(s,0.42,4.36,5.18,4.10,{shadow:false});
  addTag(s,'EDITORIAL VIEW',0.64,4.61,1.28,C.navy,'E6EBEF');
  addText(s,'현재 가격은 AI 메모리 수요 붕괴를 확정했다기보다, 높아진 이익 기대와 밸류에이션을 다시 맞추는 과정에 수급 구조가 변동성을 더한 모습에 가깝다. 한국투자증권은 단기 이익 추정치를 낮추면서도 HBM 공급 제약과 장기공급계약을 근거로 업종 비중확대를 유지했다.',0.64,5.05,4.72,1.18,{fontSize:9.8,color:C.ink,valign:'top',breakLine:true});
  addText(s,'이 때문에 레버리지 ETF를 “주범”으로만 설명하는 것도, 오늘 반등을 “업황 이상 없음”으로만 해석하는 것도 둘 다 과도하다. ETF 리밸런싱은 장 후반 낙폭을 키울 수 있지만 오전 충격의 단독 원인으로는 설명력이 낮고, 단기 실적 기대치 하향은 실제 부담이다.',0.64,6.37,4.72,1.18,{fontSize:9.8,color:C.ink,valign:'top',breakLine:true});
  addText(s,'다음 판단은 ASML 경영진이 메모리 고객사의 주문과 투자 일정을 어떻게 표현하는지, 그리고 TSMC의 강한 매출이 가이던스로 이어지는지에 달려 있다. 주문 지연 언급이 나오면 펀더멘털 훼손 해석이 강해지고, 견조한 주문과 한국 반도체 외국인 매수가 이어지면 기대치 재조정 해석이 우세해진다.',0.64,7.69,4.72,0.61,{fontSize:9.5,color:C.ink,valign:'top',breakLine:true});

  addCard(s,5.82,4.36,2.01,2.17,{fill:C.navy,line:C.navy,shadow:false});
  addText(s,'현재 결론',6.03,4.59,1.56,0.22,{fontFace:'NanumSquare',fontSize:8.3,bold:true,color:'8FE0D8'});
  addText(s,'업황 붕괴  X\n단순 저가매수 X\n\n기대치 재조정\n+ 수급 증폭',6.03,5.04,1.56,1.20,{fontFace:'NanumSquare',fontSize:13,bold:true,color:C.white,valign:'top',breakLine:true,align:'center'});

  addCard(s,5.82,6.77,2.01,1.69,{shadow:false});
  addText(s,'다음 확인점',6.03,6.99,1.56,0.22,{fontFace:'NanumSquare',fontSize:8.3,bold:true,color:C.navy});
  addText(s,'15:00  ETF 회의\n21:30  미국 CPI\n7/15 14:00  ASML\n7/16  TSMC',6.03,7.37,1.56,0.84,{fontFace:'NanumSquare',fontSize:8.7,bold:true,color:C.darkGray,valign:'top',breakLine:true});

  addText(s,'진행자 질문',0.42,8.79,7.41,0.28,{fontFace:'NanumSquare',fontSize:12.5,bold:true,color:C.navy});
  const qs=editorial.host_questions;
  qs.forEach((q,i)=>{
    addTag(s,`${i+1}`,0.42,9.23+i*0.48,0.35,C.teal,C.tealLite);
    addText(s,q,0.90,9.20+i*0.48,6.90,0.36,{fontSize:8.7,color:C.ink,valign:'top'});
  });

  addCard(s,0.42,10.70,7.41,0.36,{fill:'E9EDF1',line:'E9EDF1',shadow:false});
  addText(s,'데모 주의: 공개 snapshot과 공개 기사 기반. 실제 방송본은 사람의 수치·논지 검토와 국내 장중 데이터 교체가 필요하다.',0.58,10.77,7.05,0.19,{fontSize:6.8,color:C.darkGray});

  addFooter(s,'Sources: Yonhap Infomax articles on SK Hynix, ASML, TSMC and leveraged ETFs; U.S. BLS calendar.','news cutoff 14:45 KST');
}

pptx.writeFile({ fileName: path.join(OUTDIR, 'nowhere_noon_brief_2026-07-14_1430KST.pptx') });
