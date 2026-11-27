import unittest
from unittest.mock import patch
import durable

def fake(total,calls):
    def db(table,params=None,method="GET",body=None,prefer=None):
        calls.append((table,method,dict(params)))
        o=int(params["offset"]);n=int(params["limit"])
        return [{"host":"h%d"%i} for i in range(o,min(o+n,total))]
    return db

class Pagination(unittest.TestCase):
    def run_all(self,total,**kw):
        calls=[]
        with patch.object(durable,"db",side_effect=fake(total,calls)):
            rows=durable.db_all("managed_stores",{"select":"host"},**kw)
        return rows,calls
    def test_zero_rows(self):
        rows,calls=self.run_all(0)
        self.assertEqual(rows,[]);self.assertEqual(len(calls),1)
    def test_under_page_single_call(self):
        rows,calls=self.run_all(400)
        self.assertEqual(len(rows),400);self.assertEqual(len(calls),1)
    def test_exactly_1000_needs_second_empty_call(self):
        rows,calls=self.run_all(1000)
        self.assertEqual(len(rows),1000);self.assertEqual([c[2]["offset"] for c in calls],["0","1000"])
    def test_2500_three_calls(self):
        rows,calls=self.run_all(2500)
        self.assertEqual(len(rows),2500);self.assertEqual([c[2]["offset"] for c in calls],["0","1000","2000"])
        self.assertEqual(len({r["host"] for r in rows}),2500)
    def test_cap_stops(self):
        rows,calls=self.run_all(5000,cap=1500)
        self.assertEqual(len(rows),1500);self.assertEqual([c[2]["limit"] for c in calls],["1000","500"])
    def test_order_always_set_and_get_only(self):
        _,calls=self.run_all(2500)
        for t,m,p in calls:
            self.assertEqual(m,"GET");self.assertTrue(p["order"])
    def test_custom_order_kept_and_limit_ignored(self):
        calls=[]
        with patch.object(durable,"db",side_effect=fake(3,calls)):
            durable.db_all("t",{"order":"id.asc","limit":"1","offset":"9"})
        self.assertEqual(calls[0][2]["order"],"id.asc");self.assertEqual(calls[0][2]["offset"],"0")
    def test_page_clamped_to_1000(self):
        _,calls=self.run_all(10,page=5000)
        self.assertEqual(calls[0][2]["limit"],"1000")
    def test_params_not_mutated(self):
        params={"select":"host","enabled":"eq.true"};before=dict(params)
        with patch.object(durable,"db",side_effect=fake(2500,[])):durable.db_all("t",params)
        self.assertEqual(params,before)
    def test_none_response_terminates(self):
        with patch.object(durable,"db",return_value=None) as m:
            self.assertEqual(durable.db_all("t"),[])
        self.assertEqual(m.call_count,1)
    def test_cap_bounds_calls_when_db_ignores_offset(self):
        with patch.object(durable,"db",side_effect=lambda *a,**k:[{"host":"x"}]*int(a[1]["limit"])) as m:
            rows=durable.db_all("t",cap=2500)
        self.assertEqual(len(rows),2500);self.assertEqual(m.call_count,3)
    def test_cap_zero_makes_no_call(self):
        with patch.object(durable,"db") as m:self.assertEqual(durable.db_all("t",cap=0),[])
        m.assert_not_called()
    def test_assortment_uses_cap_5000_and_stable_order(self):
        import demand
        with patch.object(demand,"db_all",return_value=[]) as m:demand.optional_assortment()
        self.assertEqual(m.call_args.kwargs["cap"],5000);self.assertIn("category",m.call_args.kwargs["order"])
if __name__=="__main__":unittest.main()
