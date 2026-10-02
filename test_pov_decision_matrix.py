from models import TirVehicle, UniqaVehicle
from compare import compare_vehicles

class A:
    def __init__(self, vin="", spz=""):
        self.vin=vin; self.spz=spz; self.identifier=vin or spz; self.pojistka=""; self.poj_od=""; self.poj_do=""

def v(**kw):
    base=dict(oid=1,vin="TESTVIN1234567890",spz="1AA1111",zeme_puvodu="CZ",stav="VYKOUPENÉ",datum_vykupu="2026-01-01",datum_prodeje="",poznamky="")
    base.update(kw); return TirVehicle(**base)

def status(vehicle, uq=False, al=False, uq_av=True, al_av=True):
    u=[UniqaVehicle(vehicle.vin,vehicle.spz)] if uq else []
    a=[A(vehicle.vin,vehicle.spz)] if al else []
    r=compare_vehicles([vehicle],u,uq_av,"UNIQA DOWN" if not uq_av else "",a,al_av,"ALLIANZ DOWN" if not al_av else "")
    return r[0].status if r else "NO_PROBLEM"

cases=[
("insured neither",v(),False,False,True,True,"CHYBÍ V UNIQA"),
("insured UNIQA",v(),True,False,True,True,"OK"),
("insured Allianz",v(),False,True,True,True,"OK"),
("insured both",v(),True,True,True,True,"OK"),
("insured source down",v(),False,False,False,True,"NELZE OVĚŘIT"),
("deposit neither",v(poznamky="DEPOZIT"),False,False,True,True,"NEPOJIŠTĚNO, ALE DEPOZIT"),
("deposit UNIQA",v(poznamky="DEPOZIT"),True,False,True,True,"DEPOZIT, ALE POJIŠTĚNÉ"),
("deposit Allianz",v(poznamky="DEPOZIT"),False,True,True,True,"DEPOZIT, ALE POJIŠTĚNÉ"),
("deposit source down",v(poznamky="DEPOZIT"),False,False,True,False,"NELZE OVĚŘIT"),
("absent neither",v(stav="NEPŘÍTOMNÉ"),False,False,True,True,"NEPŘÍTOMNÉ, ALE NEPOJIŠTĚNÉ"),
("absent UNIQA",v(stav="NEPŘÍTOMNÉ"),True,False,True,True,"NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ"),
("absent Allianz",v(stav="NEPŘÍTOMNÉ"),False,True,True,True,"NEPŘÍTOMNÉ, ALE POJIŠTĚNÉ"),
("absent source down",v(stav="NEPŘÍTOMNÉ"),False,False,False,True,"NELZE OVĚŘIT"),
("sold neither",v(stav="PRODANÉ",datum_prodeje="2023-11-30"),False,False,True,True,"NO_PROBLEM"),
("sold UNIQA",v(stav="PRODANÉ",datum_prodeje="2023-11-30"),True,False,True,True,"PRODANÉ, ALE POJIŠTĚNÉ"),
("sold Allianz",v(stav="PRODANÉ",datum_prodeje="2023-11-30"),False,True,True,True,"PRODANÉ, ALE POJIŠTĚNÉ"),
("sold source down",v(stav="PRODANÉ",datum_prodeje="2023-11-30"),False,False,True,False,"NELZE OVĚŘIT"),
("repurchased historical sale insured",v(stav="VYKOUPENÉ",datum_prodeje="2023-11-30",datum_vykupu="2026-01-01"),True,False,True,True,"OK"),
("repurchased historical sale uninsured",v(stav="VYKOUPENÉ",datum_prodeje="2023-11-30",datum_vykupu="2026-01-01"),False,False,True,True,"CHYBÍ V UNIQA"),
]
for name,vehicle,uq,al,uq_av,al_av,expected in cases:
    got=status(vehicle,uq,al,uq_av,al_av)
    assert got==expected, f"{name}: expected {expected}, got {got}"
print(f"OK: {len(cases)} POV decision cases")
