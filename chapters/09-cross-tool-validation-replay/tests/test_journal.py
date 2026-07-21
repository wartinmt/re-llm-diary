import json
from journal import EventJournal, JournalError
from common import RuntimeCase

class JournalTests(RuntimeCase):
    def test_19_empty(self): self.assertEqual(EventJournal(self.root/"j.jsonl").read(), [])
    def test_20_append(self):
        j=EventJournal(self.root/"j.jsonl"); e=j.append("w","a",{}); self.assertEqual(e["seq"],1)
    def test_21_sequence(self):
        j=EventJournal(self.root/"j.jsonl"); j.append("w","a",{}); j.append("w","b",{}); self.assertEqual(j.read()[1]["seq"],2)
    def test_22_filter(self):
        j=EventJournal(self.root/"j.jsonl"); j.append("a","x",{}); j.append("b","x",{}); self.assertEqual(len(j.for_workflow("a")),1)
    def test_23_hash_chain(self):
        j=EventJournal(self.root/"j.jsonl"); a=j.append("w","a",{}); b=j.append("w","b",{}); self.assertEqual(b["prev_hash"],a["event_hash"])
    def test_24_tamper_detected(self):
        j=EventJournal(self.root/"j.jsonl"); j.append("w","a",{"x":1}); p=j.path; p.write_text(p.read_text().replace('"x": 1','"x": 2'),encoding="utf-8")
        with self.assertRaises(JournalError): j.read()
    def test_25_seq_detected(self):
        j=EventJournal(self.root/"j.jsonl"); j.append("w","a",{}); data=json.loads(j.path.read_text()); data["seq"]=2; j.path.write_text(json.dumps(data)+"\n")
        with self.assertRaises(JournalError): j.read()
    def test_26_prev_detected(self):
        j=EventJournal(self.root/"j.jsonl"); j.append("w","a",{}); j.append("w","b",{}); lines=j.path.read_text().splitlines(); d=json.loads(lines[1]); d["prev_hash"]="x"; lines[1]=json.dumps(d); j.path.write_text("\n".join(lines)+"\n")
        with self.assertRaises(JournalError): j.read()
    def test_27_partial_detected(self):
        p=self.root/"j.jsonl"; p.write_text("{",encoding="utf-8")
        with self.assertRaises(JournalError): EventJournal(p).read()
    def test_28_blank_detected(self):
        p=self.root/"j.jsonl"; p.write_text("\n",encoding="utf-8")
        with self.assertRaises(JournalError): EventJournal(p).read()
