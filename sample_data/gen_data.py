"""Generate the fictional Sharma Traders dataset for OpsPilot (deterministic)."""
import random, math, csv, json, datetime as dt
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

random.seed(42)
OUT = Path(__file__).resolve().parent; OUT.mkdir(parents=True, exist_ok=True)
TODAY = dt.date(2026, 9, 24)
START = TODAY - dt.timedelta(days=89)

# ---------------- suppliers ----------------
suppliers = [
  dict(id="SUP01", name="Kiran Cables Pvt Ltd", phone="+91 98220 11401", email="orders@kirancables.example", lead_time_days=5, payment_terms="30 days", categories="Wires & Cables"),
  dict(id="SUP02", name="Volta Switchgear", phone="+91 98901 22873", email="sales@voltasg.example", lead_time_days=7, payment_terms="45 days", categories="MCBs, DBs, Switchgear"),
  dict(id="SUP03", name="Brightline LED Co.", phone="+91 97654 33120", email="dispatch@brightline.example", lead_time_days=4, payment_terms="30 days", categories="LED Lighting"),
  dict(id="SUP04", name="Sai Conduits & Pipes", phone="+91 99700 45521", email="saiconduits@example.com", lead_time_days=3, payment_terms="15 days", categories="Conduits, Fittings"),
  dict(id="SUP05", name="Modula Switches", phone="+91 98500 56342", email="orders@modula.example", lead_time_days=6, payment_terms="30 days", categories="Switches & Sockets"),
  dict(id="SUP06", name="Prakash Tools & Accessories", phone="+91 90110 67789", email="prakashtools@example.com", lead_time_days=2, payment_terms="Advance", categories="Tapes, Tools, Accessories"),
]
SUP = {s["id"]: s for s in suppliers}

# ---------------- products ----------------
# (name, aliases, unit, pack, cost, sell, supplier, avg_daily_demand)
P = [
 ("FR PVC Wire 1.0 sqmm 90m","1mm wire;1 mm taar;wire 1","coil",10,1150,1390,"SUP01",1.2),
 ("FR PVC Wire 1.5 sqmm 90m","1.5mm wire;1.5 taar;dedh mm wire","coil",10,1620,1950,"SUP01",3.4),
 ("FR PVC Wire 2.5 sqmm 90m","2.5mm wire;2.5 taar;dhai mm wire","coil",10,2580,3090,"SUP01",2.8),
 ("FR PVC Wire 4.0 sqmm 90m","4mm wire;4 mm taar;char mm","coil",5,4120,4890,"SUP01",0.9),
 ("FR PVC Wire 6.0 sqmm 90m","6mm wire;6 mm taar;wire 6;6 sqmm","coil",5,6150,7290,"SUP01",0.7),
 ("Flexible Cable 3 Core 1.5 sqmm 100m","3 core cable;3core 1.5;flexible 3 core","coil",5,5400,6350,"SUP01",0.5),
 ("Coaxial Cable RG6 100m","rg6;coaxial;tv cable","coil",5,1850,2250,"SUP01",0.3),
 ("LAN Cable Cat6 305m","cat6;lan cable;network cable","box",2,5200,6150,"SUP01",0.2),
 ("MCB 6A Single Pole","6a mcb;mcb 6 amp;6 amp mcb","piece",12,118,165,"SUP02",4.0),
 ("MCB 16A Single Pole","16a mcb;mcb 16;16 amp mcb","piece",12,125,175,"SUP02",5.5),
 ("MCB 32A Double Pole","32a dp mcb;32 amp dp;dp mcb 32","piece",6,420,560,"SUP02",1.1),
 ("RCCB 40A 4 Pole 30mA","rccb 40;rccb;elcb 40","piece",4,1650,2150,"SUP02",0.4),
 ("Distribution Board 8 Way SPN","8 way db;db 8 way;8way","piece",4,980,1290,"SUP02",0.6),
 ("Distribution Board 12 Way TPN","12 way db;tpn db 12;12way","piece",2,2450,3150,"SUP02",0.2),
 ("Changeover Switch 63A","changeover 63;63a changeover;c/o switch","piece",4,1350,1750,"SUP02",0.3),
 ("Isolator 63A 4 Pole","isolator 63;63a isolator","piece",4,890,1190,"SUP02",0.2),
 ("LED Bulb 9W Cool White","9w bulb;9 watt bulb;led 9w","piece",50,48,75,"SUP03",14.0),
 ("LED Bulb 12W Cool White","12w bulb;12 watt;led 12w","piece",50,62,95,"SUP03",8.5),
 ("LED Bulb 18W Cool White","18w bulb;18 watt bulb","piece",50,96,145,"SUP03",3.0),
 ("LED Tube Light 20W 4ft","tube light;20w tube;4 ft tube","piece",25,135,199,"SUP03",6.0),
 ("LED Panel Light 15W Round","15w panel;round panel 15;panel light","piece",20,210,315,"SUP03",2.5),
 ("LED Panel Light 18W Square","18w square panel;square panel","piece",20,245,360,"SUP03",1.8),
 ("LED Flood Light 50W","50w flood;flood light 50","piece",10,640,890,"SUP03",0.8),
 ("LED Street Light 30W","street light 30;30w street","piece",10,720,990,"SUP03",0.3),
 ("LED Strip 5m Warm White","led strip;strip light;5m strip","roll",10,280,420,"SUP03",1.5),
 ("PVC Conduit Pipe 20mm 3m","20mm pipe;conduit 20;pipe 20 mm","length",50,38,58,"SUP04",18.0),
 ("PVC Conduit Pipe 25mm 3m","25mm pipe;conduit 25;pipe 25","length",50,52,78,"SUP04",9.0),
 ("Conduit Bend 20mm","20mm bend;bend 20","piece",100,6,11,"SUP04",22.0),
 ("Conduit Junction Box 20mm 2-Way","junction box;jn box 20;2 way box","piece",100,9,16,"SUP04",15.0),
 ("Casing Capping 1 inch 2m","casing 1 inch;capping 1;1 inch casing","length",50,34,52,"SUP04",7.0),
 ("GI Box 3 Module","3m box;3 module box;gi box 3","piece",50,28,45,"SUP04",6.5),
 ("GI Box 6 Module","6m box;6 module box;gi box 6","piece",50,42,66,"SUP04",4.2),
 ("GI Box 8 Module","8m box;8 module box;gi box 8","piece",25,55,85,"SUP04",2.0),
 ("Flexible Pipe 20mm 50m","flexible pipe;flexi pipe 20","roll",5,420,590,"SUP04",0.6),
 ("Modular Switch 6A 1-Way","6a switch;switch 6 amp;1 way switch","piece",100,22,38,"SUP05",30.0),
 ("Modular Switch 16A 1-Way","16a switch;power switch;switch 16","piece",50,48,75,"SUP05",8.0),
 ("Modular Socket 6A 3-Pin","6a socket;socket 6;3 pin socket","piece",50,58,88,"SUP05",12.0),
 ("Modular Socket 16A 3-Pin","16a socket;power socket;socket 16","piece",25,96,145,"SUP05",4.5),
 ("Fan Regulator Modular","regulator;fan regulator;step regulator","piece",20,145,215,"SUP05",3.5),
 ("Bell Push Modular","bell push;bell switch","piece",50,32,52,"SUP05",1.2),
 ("Plate 3 Module White","3m plate;3 module plate","piece",50,34,55,"SUP05",6.0),
 ("Plate 6 Module White","6m plate;6 module plate","piece",50,52,82,"SUP05",4.0),
 ("Plate 8 Module White","8m plate;8 module plate","piece",25,68,105,"SUP05",1.8),
 ("USB Charger Socket 2.1A","usb socket;usb charger;usb point","piece",20,310,450,"SUP05",0.9),
 ("TV Socket Modular","tv socket;tv point","piece",50,40,65,"SUP05",1.0),
 ("Blank Plate 1 Module","blank;blank plate;blank module","piece",100,8,15,"SUP05",5.0),
 ("PVC Insulation Tape Black","black tape;insulation tape;tape","roll",100,9,16,"SUP06",25.0),
 ("PVC Insulation Tape Red","red tape","roll",100,9,16,"SUP06",6.0),
 ("Cable Tie 200mm (100 pcs)","cable tie;tie 200;zip tie","packet",20,45,70,"SUP06",4.0),
 ("Screw 8x1 inch (100 pcs)","screw 8x1;screws;pech","packet",20,55,85,"SUP06",6.0),
 ("Wall Plug 6mm (100 pcs)","gitti;wall plug;rawl plug","packet",20,35,55,"SUP06",5.5),
 ("Cable Clip 6mm (100 pcs)","clip 6mm;cable clip;clips","packet",20,28,45,"SUP06",3.0),
 ("Tester Screwdriver","tester;line tester","piece",50,22,40,"SUP06",2.5),
 ("Combination Plier 8 inch","plier;pakkad;combination plier","piece",10,165,240,"SUP06",0.8),
 ("Wire Stripper","stripper;wire stripper","piece",10,140,210,"SUP06",0.5),
 ("Multi Plug Adapter 3 Pin","multiplug;adapter;3 pin adapter","piece",50,38,65,"SUP06",4.0),
 ("Extension Board 4 Socket 3m","extension board;extension;spike guard 4","piece",10,265,390,"SUP06",2.2),
 ("Doorbell Wired Musical","door bell;bell;calling bell","piece",10,180,260,"SUP06",0.7),
 ("Earthing Wire GI 8 SWG 1kg","earthing wire;gi wire;earth wire","kg",10,95,140,"SUP06",1.5),
 ("Copper Lug 16 sqmm (pack of 10)","lug 16;copper lug","packet",10,120,175,"SUP06",0.6),
]
products=[]
for i,(n,al,u,pack,c,s,sup,d) in enumerate(P,1):
    products.append(dict(sku=f"ST-{i:04d}",name=n,aliases=al,unit=u,pack_size=pack,cost_price=c,sell_price=s,supplier_id=sup,avg_daily=d))

# ---------------- customers ----------------
areas=["Hadapsar","Kothrud","Wakad","Hinjewadi","Baner","Pimpri","Chinchwad","Kharadi","Katraj","Bibwewadi","Warje","Aundh","Viman Nagar","Wagholi","Dhayari"]
shops=[("Ramesh Electricals","Ramesh Patil"),("Shree Ganesh Electric","Sunil Jadhav"),("Om Sai Hardware","Prakash Kulkarni"),("Jai Bhavani Electricals","Anil Shinde"),
("New Light House","Imran Shaikh"),("Mahalaxmi Traders","Santosh Pawar"),("Deshmukh Electric Works","Rahul Deshmukh"),("Kalpana Lighting","Kalpana Joshi"),
("Balaji Electricals","Venkat Rao"),("Royal Hardware","Farhan Khan"),("Siddhivinayak Electric","Mahesh Gaikwad"),("Pooja Electricals","Nitin Bhosale"),
("A1 Electric Store","Arjun Mehta"),("Swami Samarth Traders","Dattatray More"),("Tulja Electricals","Ganesh Kale"),("Vighnaharta Hardware","Sachin Wagh"),
("Patil Electric Mart","Vijay Patil"),("Krishna Light Centre","Kishor Yadav"),("Laxmi Narayan Electric","Suresh Agarwal"),("City Electricals","Deepak Jain"),
("Sahyadri Electric","Amol Chavan"),("Modern Electric Co.","Rohit Kapoor"),("Shivam Hardware","Shivam Tiwari"),("Gajanan Electricals","Sandeep Mane"),("Star Electric House","Zubin Irani")]
customers=[]
for i,(shop,cont) in enumerate(shops,1):
    customers.append(dict(id=f"CUS{i:03d}",shop_name=shop,contact=cont,phone=f"98{random.randint(10000000,99999999)}",area=areas[(i-1)%len(areas)],
        credit_limit=random.choice([50000,75000,100000,150000,200000]),payment_terms_days=random.choice([15,30,30,45])))
CUS={c["id"]:c for c in customers}
# customer "size" weight
cw={c["id"]:random.uniform(0.4,2.2) for c in customers}

# ---------------- sales history (90 days) ----------------
sales=[]; billno=1000
for d in range(90):
    day=START+dt.timedelta(days=d)
    if day.weekday()==6: continue  # closed Sundays
    for p in products:
        lam=p["avg_daily"]*7/6
        # poisson-ish
        q=0; L=math.exp(-lam); k=0; pr=1
        while True:
            pr*=random.random()
            if pr<L: break
            k+=1
        q=k
        while q>0:
            c=random.choices(customers,weights=[cw[x["id"]] for x in customers])[0]
            take=min(q,max(1,int(random.expovariate(1/ max(1,p["avg_daily"]/2)))+1))
            sales.append(dict(date=day.isoformat(),customer_id=c["id"],sku=p["sku"],qty=take,unit_price=p["sell_price"],amount=take*p["sell_price"]))
            q-=take
# actual avg daily from history (per calendar day, 90 days)
hist={p["sku"]:0 for p in products}
for s in sales: hist[s["sku"]]+=s["qty"]
for p in products: p["hist_avg_daily"]=round(hist[p["sku"]]/90,2)

# ---------------- stock on hand ----------------
SAFETY_DAYS=3; COVER_DAYS=30
low_pick=["ST-0002","ST-0005","ST-0010","ST-0017","ST-0026","ST-0035","ST-0047","ST-0021","ST-0012"]
open_po={"ST-0021":40}  # already on order -> covers it; agent should NOT reorder
for p in products:
    d=p["hist_avg_daily"]; lt=SUP[p["supplier_id"]]["lead_time_days"]
    rop=d*lt+d*SAFETY_DAYS
    p["reorder_point"]=round(rop,1)
    if p["sku"] in low_pick:
        p["on_hand"]=max(0,int(rop*random.uniform(0.2,0.7)))
    else:
        p["on_hand"]=int(rop*random.uniform(1.4,4.0))+p["pack_size"]//2
# one zero stock
for p in products:
    if p["sku"]=="ST-0047": p["on_hand"]=0

expected_reorders=[]
for p in products:
    d=p["hist_avg_daily"]; lt=SUP[p["supplier_id"]]["lead_time_days"]
    onorder=open_po.get(p["sku"],0)
    if p["on_hand"]+onorder <= p["reorder_point"]:
        need=d*(lt+COVER_DAYS)-p["on_hand"]-onorder
        qty=math.ceil(need/p["pack_size"])*p["pack_size"]
        expected_reorders.append(dict(sku=p["sku"],name=p["name"],supplier=SUP[p["supplier_id"]]["name"],on_hand=p["on_hand"],on_order=onorder,
            avg_daily=d,lead_time_days=lt,reorder_point=p["reorder_point"],reorder_qty=qty,est_cost=qty*p["cost_price"],
            days_of_cover=round(p["on_hand"]/d,1) if d else None))

# ---------------- stock_register.xlsx (messy) ----------------
wb=openpyxl.Workbook(); ws=wb.active; ws.title="Stock Sep"
ws["A1"]="SHARMA TRADERS - STOCK REGISTER"; ws["A1"].font=Font(bold=True,size=14)
ws["A2"]="Updated by Ravi on 24/9 evening (godown count)"
hdr=["Item Code","Item Name","Unit","Qty In Stock","Rate (Purchase)","MRP / Sale Rate","Supplier","Remarks"]
ws.append([]); ws.append(hdr)
for c in ws[4]: c.font=Font(bold=True); c.fill=PatternFill("solid",fgColor="FFF2CC")
issues=[]
unit_variants={"coil":["coil","Coil","COIL","coils"],"piece":["pcs","Pcs","piece","nos","NOS"],"box":["box","Box"],"length":["length","len","Lgth"],
               "roll":["roll","Roll"],"packet":["pkt","packet","Pkt"],"kg":["kg","KG","Kg"]}
rows=[]
for p in products:
    code=p["sku"]; name=p["name"]; unit=random.choice(unit_variants[p["unit"]]); qty=p["on_hand"]; cost=p["cost_price"]; sell=p["sell_price"]
    sup=SUP[p["supplier_id"]]["name"]; rem=""
    rows.append([code,name,unit,qty,cost,sell,sup,rem])
# plant problems
PM0={p["sku"]:p["name"] for p in products}
def setrow(sku,col,val,itype,detail):
    for r in rows:
        if r[0]==sku: r[col]=val; issues.append(dict(file="stock_register.xlsx",sku=sku,issue=itype,detail=detail)); return
setrow("ST-0009",4,None,"missing_value","Purchase rate blank for MCB 6A")
setrow("ST-0019",5,None,"missing_value","Sale rate blank for LED Bulb 18W")
r=[x for x in rows if x[0]=="ST-0028"][0]; r[3]=f"{r[3]} pcs"; issues.append(dict(file="stock_register.xlsx",sku="ST-0028",issue="qty_as_text",detail=f"Qty written as text '{r[3]}'"))
r=[x for x in rows if x[0]=="ST-0040"][0]; r[3]=-4; issues.append(dict(file="stock_register.xlsx",sku="ST-0040",issue="negative_qty",detail="Qty is -4 (likely counting error)"))
r=[x for x in rows if x[0]=="ST-0033"][0]; r[1]="  gi box 8 module  "; issues.append(dict(file="stock_register.xlsx",sku="ST-0033",issue="name_format",detail="Name lower-case with extra spaces"))
r=[x for x in rows if x[0]=="ST-0052"][0]; r[0]=None; issues.append(dict(file="stock_register.xlsx",sku="ST-0052",issue="missing_code",detail=f"Item code blank for '{PM0['ST-0052']}' - match by name"))
r=[x for x in rows if x[0]=="ST-0021"][0]; r[7]="40 pcs ordered from Brightline on 22/9"
dup=list([x for x in rows if x[0]=="ST-0036"][0]); dup[3]=dup[3]+7; dup[7]="recount"
issues.append(dict(file="stock_register.xlsx",sku="ST-0036",issue="duplicate_row",detail=f"Appears twice with different qty ({[x for x in rows if x[0]=='ST-0036'][0][3]} and {dup[3]}); latest row says 'recount'"))
r=[x for x in rows if x[0]=="ST-0014"][0]; r[6]="Volta"; issues.append(dict(file="stock_register.xlsx",sku="ST-0014",issue="supplier_alias",detail="Supplier written as 'Volta' (= Volta Switchgear)"))
r=[x for x in rows if x[0]=="ST-0047"][0]; r[7]="finished!! order urgent"
random.shuffle(rows)
insert_at=[i for i,x in enumerate(rows) if x[0]=="ST-0036"][0]+random.randint(5,15)
rows.insert(min(insert_at,len(rows)),dup)
rows.insert(30,[None,"--- Switches & Sockets (Modula) ---",None,None,None,None,None,None]); issues.append(dict(file="stock_register.xlsx",sku=None,issue="section_header_row",detail="A text-only section header row sits in the middle of the data"))
rows.append([None,"Old stock - Tube light 36W (discontinued)","pcs",11,90,150,"Brightline",""]); issues.append(dict(file="stock_register.xlsx",sku=None,issue="unknown_item",detail="Discontinued item not in product master"))
for r in rows: ws.append(r)
ws.append([]); ws.append([None,"TOTAL ITEMS",None,"=COUNTA(B5:B200)"])
issues.append(dict(file="stock_register.xlsx",sku=None,issue="footer_row",detail="Totals row at the bottom of the sheet"))
ws2=wb.create_sheet("Notes"); ws2["A1"]="Godown 2 stock not counted this week"; ws2["A2"]="Ravi to recheck MCB and switch stock"
for col,w in zip("ABCDEFGH",[12,40,9,14,16,16,28,36]): ws.column_dimensions[col].width=w
wb.save(OUT/"stock_register.xlsx")

# ---------------- product master (clean-ish reference with aliases) ----------------
with open(OUT/"product_master.csv","w",newline="",encoding="utf-8") as f:
    w=csv.writer(f); w.writerow(["sku","name","aliases","unit","pack_size","cost_price","sell_price","supplier_id"])
    for p in products: w.writerow([p["sku"],p["name"],p["aliases"],p["unit"],p["pack_size"],p["cost_price"],p["sell_price"],p["supplier_id"]])

# ---------------- suppliers.csv ----------------
with open(OUT/"suppliers.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=list(suppliers[0].keys())); w.writeheader(); w.writerows(suppliers)

# ---------------- customers.xlsx (messy) ----------------
wb=openpyxl.Workbook(); ws=wb.active; ws.title="Parties"
ws.append(["Party Code","Shop Name","Contact Person","Mobile","Area","Credit Limit (Rs)","Credit Days"])
for c in ws[1]: c.font=Font(bold=True)
for c in customers:
    ph=c["phone"]; fmt=random.choice([ph,"+91 "+ph[:5]+" "+ph[5:],"0"+ph,ph[:5]+"-"+ph[5:]])
    ws.append([c["id"],c["shop_name"],c["contact"],fmt,c["area"],c["credit_limit"],c["payment_terms_days"]])
ws.append([None,"Ramesh Electrical","Ramesh",customers[0]["phone"],"Hadapsar",None,None])
issues.append(dict(file="customers.xlsx",sku=None,issue="duplicate_customer",detail="'Ramesh Electrical' (no code) is the same shop as CUS001 'Ramesh Electricals' - same mobile"))
issues.append(dict(file="customers.xlsx",sku=None,issue="phone_formats",detail="Mobile numbers in 4 different formats (+91, leading 0, dash, plain)"))
for col,w in zip("ABCDEFG",[11,28,20,18,14,16,12]): ws.column_dimensions[col].width=w
wb.save(OUT/"customers.xlsx")

# ---------------- outstanding_dues.xlsx ----------------
dues=[]; bill=5100
for c in customers:
    n=random.randint(1,3)
    for _ in range(n):
        bill+=random.randint(1,9)
        age=random.randint(3,40)
        bdate=TODAY-dt.timedelta(days=age)
        amt=random.randint(8,60)*500
        paid=0
        dues.append(dict(customer_id=c["id"],bill_no=f"ST/{bill}",bill_date=bdate,amount=amt,paid=paid))
# force specific overdue / over-limit situations
def cust(i): return customers[i-1]["id"]
dues.append(dict(customer_id=cust(3),bill_no="ST/5402",bill_date=TODAY-dt.timedelta(days=62),amount=48500,paid=10000))
dues.append(dict(customer_id=cust(10),bill_no="ST/5410",bill_date=TODAY-dt.timedelta(days=55),amount=86000,paid=0))
dues.append(dict(customer_id=cust(10),bill_no="ST/5433",bill_date=TODAY-dt.timedelta(days=20),amount=71000,paid=0))
dues.append(dict(customer_id=cust(17),bill_no="ST/5451",bill_date=TODAY-dt.timedelta(days=48),amount=39000,paid=15000))
wb=openpyxl.Workbook(); ws=wb.active; ws.title="Outstanding"
ws.append(["Party","Bill No","Bill Date","Bill Amt","Received","Balance"])
for c in ws[1]: c.font=Font(bold=True)
for i,dd in enumerate(sorted(dues,key=lambda x:x["bill_date"])):
    c=CUS[dd["customer_id"]]
    datev = dd["bill_date"].strftime("%d-%m-%Y") if i%7==3 else dd["bill_date"]
    ws.append([c["shop_name"],dd["bill_no"],datev,dd["amount"],dd["paid"] or None,dd["amount"]-dd["paid"]])
    if not isinstance(datev,str): ws.cell(ws.max_row,3).number_format="DD/MM/YYYY"
issues.append(dict(file="outstanding_dues.xlsx",sku=None,issue="mixed_date_types",detail="Some bill dates are real dates, some are text 'DD-MM-YYYY'"))
issues.append(dict(file="outstanding_dues.xlsx",sku=None,issue="party_by_name",detail="Rows reference customers by shop name, not party code"))
for col,w in zip("ABCDEF",[28,12,13,12,12,12]): ws.column_dimensions[col].width=w
wb.save(OUT/"outstanding_dues.xlsx")

# expected payment actions (policy: remind if overdue >=7 days past credit days; hold if overdue >30 or balance > credit limit)
bal={}; overdue=[]
for dd in dues:
    c=CUS[dd["customer_id"]]; b=dd["amount"]-dd["paid"]; bal[c["id"]]=bal.get(c["id"],0)+b
    due=dd["bill_date"]+dt.timedelta(days=c["payment_terms_days"]); od=(TODAY-due).days
    if b>0 and od>=7: overdue.append(dict(customer_id=c["id"],shop=c["shop_name"],bill_no=dd["bill_no"],balance=b,days_overdue=od))
pay_actions=[]
for cid in sorted(set([o["customer_id"] for o in overdue])|{k for k,v in bal.items() if v>CUS[k]["credit_limit"]}):
    c=CUS[cid]; ods=[o for o in overdue if o["customer_id"]==cid]; maxod=max([o["days_overdue"] for o in ods],default=0)
    action="HOLD_NEW_ORDERS" if (maxod>30 or bal[cid]>c["credit_limit"]) else "SEND_REMINDER"
    pay_actions.append(dict(customer_id=cid,shop=c["shop_name"],total_balance=bal[cid],credit_limit=c["credit_limit"],over_limit=bal[cid]>c["credit_limit"],
        overdue_bills=[o["bill_no"] for o in ods],max_days_overdue=maxod,expected_action=action))

# ---------------- WhatsApp export ----------------
def ts(d,h,m): 
    ap="am" if h<12 else "pm"; hh=h if 1<=h<=12 else (h-12 if h>12 else 12)
    return f"{d.day:02d}/{d.month:02d}/{str(d.year)[2:]}, {hh}:{m:02d} {ap}"
D1,D2,D3=TODAY-dt.timedelta(days=2),TODAY-dt.timedelta(days=1),TODAY
OWN="Sharma Traders"
msgs=[
 (D1,9,12,"Ramesh Electricals","Good morning bhai"),
 (D1,9,13,"Ramesh Electricals","20 box 1.5mm wire, 10 pkt gitti aur 50 black tape bhejo aaj"),
 (D1,9,20,OWN,"Ok Rameshbhai, shaam tak"),
 (D1,10,5,"Om Sai Hardware","Sir 6a switch 200 pcs\n6a socket 100 pcs\nplate 3m 50"),
 (D1,10,41,"New Light House","9w bulb 300, 12w bulb 150, tube light 40"),
 (D1,11,2,"New Light House","<Media omitted>"),
 (D1,11,3,"New Light House","ye wala panel bhi 20 chahiye"),
 (D1,12,30,"Balaji Electricals","MCB 16 amp 24 nos, 6 amp 12 nos. DB 8 way 2"),
 (D1,14,15,"Kalpana Lighting","Hello, need 10 LED strip and 5 flood light 50w. Also do you have smart wifi bulbs?"),
 (D1,16,48,"Ramesh Electricals","1.5 wala 20 nahi 15 karo, sorry"),
 (D1,17,2,"Mahalaxmi Traders","20mm pipe 100 length, bend 200, jn box 100"),
 (D1,18,10,"Mahalaxmi Traders","Payment next week pakka 🙏"),
 (D2,9,30,"Royal Hardware","Bhai 2.5 taar 200 coil urgent chahiye site ke liye"),
 (D2,9,31,OWN,"200 coil? Itna stock nahi hai, confirm karo"),
 (D2,9,45,"Royal Hardware","haan 200, bada project mila hai"),
 (D2,10,20,"Deshmukh Electric Works","rccb 40 - 2, 32a dp mcb 4, changeover 63 - 1"),
 (D2,11,0,"Siddhivinayak Electric","Regulator 10, bell push 10, usb socket 5"),
 (D2,12,12,"Jai Bhavani Electricals","ok"),
 (D2,13,40,"Pooja Electricals","Casing 1 inch 40, 3m box 30, 6m box 20, 6m plate 20"),
 (D2,15,5,"City Electricals","extension board 10, multiplug 50, tester 20"),
 (D2,15,6,"City Electricals","aur ek 4mm wire coil"),
 (D2,17,55,"A1 Electric Store","Pls send rate list for LED panels"),
 (D3,9,5,"Swami Samarth Traders","6 mm taar 5 coil, earth wire 10 kg"),
 (D3,9,50,"Om Sai Hardware","kal wala order mein switch 200 ki jagah 150 kar dena"),
 (D3,10,30,"Patil Electric Mart","18w square panel 15, 15w panel 25, flood 50w 3"),
 (D3,11,15,"Gajanan Electricals","cat6 1 box aur rg6 2 coil"),
 (D3,12,0,"Tulja Electricals","black tape 100, red tape 20, cable tie 10 pkt, clip 10 pkt"),
 (D3,12,1,"Tulja Electricals","<Media omitted>"),
 (D3,14,20,"Shivam Hardware","Solar panel 2 kw ka rate kya hai?"),
 (D3,16,40,"Krishna Light Centre","9w bulb 100 aur door bell 5"),
]
with open(OUT/"whatsapp_orders_export.txt","w",encoding="utf-8") as f:
    f.write(f"{ts(D1,9,0)} - Messages and calls are end-to-end encrypted. Only people in this chat can read, listen to, or share them.\n")
    for d,h,m,who,txt in msgs:
        lines=txt.split("\n"); f.write(f"{ts(d,h,m)} - {who}: {lines[0]}\n")
        for l in lines[1:]: f.write(l+"\n")

sku_by_name={p["name"]:p["sku"] for p in products}
def S(n): return sku_by_name[n]
expected_orders=[
 dict(customer="Ramesh Electricals",items=[(S("FR PVC Wire 1.5 sqmm 90m"),15),(S("Wall Plug 6mm (100 pcs)"),10),(S("PVC Insulation Tape Black"),50)],note="1.5mm wire corrected from 20 to 15 by a later message; '20 box' of wire means 20 coils"),
 dict(customer="Om Sai Hardware",items=[(S("Modular Switch 6A 1-Way"),150),(S("Modular Socket 6A 3-Pin"),100),(S("Plate 3 Module White"),50)],note="Switch qty corrected 200→150 next day; multi-line message"),
 dict(customer="New Light House",items=[(S("LED Bulb 9W Cool White"),300),(S("LED Bulb 12W Cool White"),150),(S("LED Tube Light 20W 4ft"),40)],note="'ye wala panel bhi 20' refers to an image - ambiguous, must go to review, not guessed"),
 dict(customer="Balaji Electricals",items=[(S("MCB 16A Single Pole"),24),(S("MCB 6A Single Pole"),12),(S("Distribution Board 8 Way SPN"),2)],note=""),
 dict(customer="Kalpana Lighting",items=[(S("LED Strip 5m Warm White"),10),(S("LED Flood Light 50W"),5)],note="'smart wifi bulbs' is not in catalogue - flag as unknown product / enquiry"),
 dict(customer="Mahalaxmi Traders",items=[(S("PVC Conduit Pipe 20mm 3m"),100),(S("Conduit Bend 20mm"),200),(S("Conduit Junction Box 20mm 2-Way"),100)],note="The follow-up payment promise is not an order line"),
 dict(customer="Royal Hardware",items=[(S("FR PVC Wire 2.5 sqmm 90m"),200)],note="ANOMALY: ~10x this customer's usual order; exceeds stock; customer is over credit limit"),
 dict(customer="Deshmukh Electric Works",items=[(S("RCCB 40A 4 Pole 30mA"),2),(S("MCB 32A Double Pole"),4),(S("Changeover Switch 63A"),1)],note=""),
 dict(customer="Siddhivinayak Electric",items=[(S("Fan Regulator Modular"),10),(S("Bell Push Modular"),10),(S("USB Charger Socket 2.1A"),5)],note=""),
 dict(customer="Pooja Electricals",items=[(S("Casing Capping 1 inch 2m"),40),(S("GI Box 3 Module"),30),(S("GI Box 6 Module"),20),(S("Plate 6 Module White"),20)],note="'3m box' = 3 module GI box, not 3 metre"),
 dict(customer="City Electricals",items=[(S("Extension Board 4 Socket 3m"),10),(S("Multi Plug Adapter 3 Pin"),50),(S("Tester Screwdriver"),20),(S("FR PVC Wire 4.0 sqmm 90m"),1)],note="Order split across two messages"),
 dict(customer="Swami Samarth Traders",items=[(S("FR PVC Wire 6.0 sqmm 90m"),5),(S("Earthing Wire GI 8 SWG 1kg"),10)],note=""),
 dict(customer="Patil Electric Mart",items=[(S("LED Panel Light 18W Square"),15),(S("LED Panel Light 15W Round"),25),(S("LED Flood Light 50W"),3)],note=""),
 dict(customer="Gajanan Electricals",items=[(S("LAN Cable Cat6 305m"),1),(S("Coaxial Cable RG6 100m"),2)],note=""),
 dict(customer="Tulja Electricals",items=[(S("PVC Insulation Tape Black"),100),(S("PVC Insulation Tape Red"),20),(S("Cable Tie 200mm (100 pcs)"),10),(S("Cable Clip 6mm (100 pcs)"),10)],note=""),
 dict(customer="Krishna Light Centre",items=[(S("LED Bulb 9W Cool White"),100),(S("Doorbell Wired Musical"),5)],note=""),
]
non_orders=[("Jai Bhavani Electricals","'ok' - no order"),("A1 Electric Store","Rate list request - enquiry, not an order"),("Shivam Hardware","Solar panel enquiry - product not stocked"),("Mahalaxmi Traders","Payment promise - not an order line")]

# Royal Hardware: make them over credit limit
rh=[c for c in customers if c["shop_name"]=="Royal Hardware"][0]
# (dues forced above for cust(10) = Royal Hardware -> check)
assert rh["id"]==cust(10)

# ---------------- supplier invoices (PDF) ----------------
def invoice_pdf(fname,sup,inv_no,inv_date,lines,note=None):
    c=canvas.Canvas(str(OUT/fname),pagesize=A4); W,H=A4; y=H-25*mm
    c.setFont("Helvetica-Bold",15); c.drawString(20*mm,y,sup["name"].upper()); y-=6*mm
    c.setFont("Helvetica",9); c.drawString(20*mm,y,f"Ph: {sup['phone']}  |  {sup['email']}  |  GSTIN: 27AAAAA{random.randint(1000,9999)}A1Z{random.randint(1,9)}"); y-=12*mm
    c.setFont("Helvetica-Bold",12); c.drawString(20*mm,y,"TAX INVOICE"); c.setFont("Helvetica",10)
    c.drawRightString(W-20*mm,y,f"Invoice No: {inv_no}"); y-=6*mm; c.drawRightString(W-20*mm,y,f"Date: {inv_date.strftime('%d.%m.%Y')}")
    c.drawString(20*mm,y,"Bill To: Sharma Traders, Budhwar Peth, Pune 411002"); y-=12*mm
    c.setFont("Helvetica-Bold",9)
    for x,t in [(20,"#"),(28,"Description"),(118,"Qty"),(135,"Rate"),(160,"Amount")]: c.drawString(x*mm,y,t)
    y-=2*mm; c.line(20*mm,y,W-20*mm,y); y-=6*mm; c.setFont("Helvetica",9); sub=0
    for i,(desc,q,r) in enumerate(lines,1):
        amt=q*r; sub+=amt
        c.drawString(20*mm,y,str(i)); c.drawString(28*mm,y,desc); c.drawString(118*mm,y,str(q)); c.drawString(135*mm,y,f"{r:,.2f}"); c.drawString(160*mm,y,f"{amt:,.2f}"); y-=6*mm
    y-=2*mm; c.line(20*mm,y,W-20*mm,y); y-=7*mm
    gst=round(sub*0.18,2)
    for lab,val in [("Sub Total",sub),("GST @18%",gst),("Grand Total",sub+gst)]:
        c.setFont("Helvetica-Bold" if lab=="Grand Total" else "Helvetica",10); c.drawString(130*mm,y,lab); c.drawRightString(W-20*mm,y,f"Rs {val:,.2f}"); y-=6*mm
    if note: y-=6*mm; c.setFont("Helvetica-Oblique",9); c.drawString(20*mm,y,note)
    c.setFont("Helvetica",8); c.drawString(20*mm,20*mm,f"Payment terms: {sup['payment_terms']}. Subject to Pune jurisdiction. E.&O.E.")
    c.save(); return sub+gst
PM={p["sku"]:p for p in products}
inv=[]
lines1=[(PM["ST-0002"]["name"],20,PM["ST-0002"]["cost_price"]),(PM["ST-0003"]["name"],20,PM["ST-0003"]["cost_price"]),(PM["ST-0004"]["name"],5,PM["ST-0004"]["cost_price"])]
inv.append(("invoice_kiran_cables_KC-2291.pdf","SUP01","KC/26-27/2291",TODAY-dt.timedelta(days=12),lines1,None))
jump=round(PM["ST-0017"]["cost_price"]*1.32,2)
lines2=[(PM["ST-0017"]["name"],200,jump),(PM["ST-0018"]["name"],100,PM["ST-0018"]["cost_price"]),(PM["ST-0020"]["name"],50,PM["ST-0020"]["cost_price"])]
inv.append(("invoice_brightline_BL-0874.pdf","SUP03","BL-0874",TODAY-dt.timedelta(days=5),lines2,"Note: revised pricing applicable from this invoice."))
lines3=[("PVC Conduit Pipe 20 mm (3 mtr)",200,PM["ST-0026"]["cost_price"]),("Bend 20mm",500,PM["ST-0028"]["cost_price"]),("Junction Box 2 way 20mm",300,PM["ST-0029"]["cost_price"])]
inv.append(("invoice_sai_conduits_SC-118.pdf","SUP04","SC-118",TODAY-dt.timedelta(days=3),lines3,None))
inv.append(("invoice_sai_conduits_SC-118_copy.pdf","SUP04","SC-118",TODAY-dt.timedelta(days=3),lines3,"DUPLICATE COPY"))
for f,s,no,d,l,n in inv: invoice_pdf(f,SUP[s],no,d,l,n)

# ---------------- company policy PDF ----------------
policy=[
 ("1. Stock and reordering",[
  "1.1 Safety stock is 3 days of average daily sales (based on the last 90 days).",
  "1.2 Reorder point = average daily sales x supplier lead time + safety stock.",
  "1.3 When stock on hand plus stock already on order is at or below the reorder point, raise a reorder.",
  "1.4 Reorder quantity = enough to cover supplier lead time + 30 days of sales, minus stock on hand and on order,",
  "    rounded UP to the supplier's pack size.",
  "1.5 Any single purchase order above Rs 1,00,000 needs the owner's approval (Mr. Vinod Sharma). Below that,",
  "    the store manager may approve. In OpsPilot every PO still needs one human approval.",
 ]),
 ("2. Customer credit",[
  "2.1 Each customer has a credit limit and credit days (see customer list).",
  "2.2 A bill is overdue when it is unpaid after its credit days.",
  "2.3 Send a polite payment reminder when any bill is 7 or more days overdue.",
  "2.4 Put new orders ON HOLD (needs owner approval to dispatch) when a customer has a bill more than",
  "    30 days overdue, or total outstanding is above the credit limit.",
  "2.5 Reminders must be polite and in simple Hinglish or English. Never threaten. Never share another",
  "    customer's details.",
 ]),
 ("3. Orders",[
  "3.1 An order that is more than 5x the customer's average order quantity for that item must be confirmed",
  "    by the owner before dispatch.",
  "3.2 If a message is unclear (for example it refers to a photo), ask the customer - do not guess.",
  "3.3 Items we do not stock should be logged as enquiries, not orders.",
 ]),
 ("4. Supplier invoices",[
  "4.1 Check every invoice line rate against the last purchase rate. A change of more than 10% must be",
  "    flagged to the owner before payment.",
  "4.2 Never pay the same invoice number from the same supplier twice.",
 ]),
]
c=canvas.Canvas(str(OUT/"company_policy.pdf"),pagesize=A4); W,H=A4; y=H-25*mm
c.setFont("Helvetica-Bold",15); c.drawString(20*mm,y,"Sharma Traders - Operating Policy"); y-=6*mm
c.setFont("Helvetica",9); c.drawString(20*mm,y,"Version 3, effective 1 April 2026. Owner: Vinod Sharma."); y-=12*mm
for head,items in policy:
    c.setFont("Helvetica-Bold",11); c.drawString(20*mm,y,head); y-=7*mm; c.setFont("Helvetica",9.5)
    for it in items: c.drawString(22*mm,y,it); y-=5.5*mm
    y-=5*mm
c.save()

# ---------------- sales_history.csv ----------------
with open(OUT/"sales_history_90d.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=["date","customer_id","sku","qty","unit_price","amount"]); w.writeheader(); w.writerows(sales)

# ---------------- answer key ----------------
avg_order={}
for s in sales:
    k=(s["customer_id"],s["sku"]); avg_order.setdefault(k,[]).append(s["qty"])
rh_avg=round(sum(avg_order.get((rh["id"],"ST-0003"),[1]))/len(avg_order.get((rh["id"],"ST-0003"),[1])),1)
anomalies=[
 dict(type="order_size",detail=f"Royal Hardware ordered 200 coils of 2.5 sqmm wire; their average order for this item is {rh_avg} coils (>5x rule 3.1). Stock on hand: {PM['ST-0003']['on_hand']}."),
 dict(type="invoice_price_jump",detail=f"Brightline invoice BL-0874 bills LED Bulb 9W at Rs {jump} vs last purchase rate Rs {PM['ST-0017']['cost_price']} (+32%, rule 4.1)."),
 dict(type="duplicate_invoice",detail="Sai Conduits invoice SC-118 received twice (second PDF marked DUPLICATE COPY) - rule 4.2."),
]
key=dict(as_of=TODAY.isoformat(),policy=dict(safety_days=SAFETY_DAYS,cover_days=COVER_DAYS),
  expected_reorders=expected_reorders,open_purchase_orders=[dict(sku=k,qty=v,note="Mentioned in stock register remarks") for k,v in open_po.items()],
  expected_payment_actions=pay_actions,expected_orders=[dict(customer=o["customer"],items=[dict(sku=a,qty=b) for a,b in o["items"]],note=o["note"]) for o in expected_orders],
  non_orders=[dict(from_=a,why=b) for a,b in non_orders],anomalies=anomalies,data_issues=issues)
(OUT/"answer_key.json").write_text(json.dumps(key,indent=2,default=str),encoding="utf-8")
print("reorders",len(expected_reorders),"pay actions",len(pay_actions),"orders",len(expected_orders),"issues",len(issues),"sales rows",len(sales))
for r in expected_reorders: print(r["sku"],r["name"][:28],r["on_hand"],r["reorder_point"],r["reorder_qty"])
for a in pay_actions: print(a["shop"],a["total_balance"],a["credit_limit"],a["max_days_overdue"],a["expected_action"])
