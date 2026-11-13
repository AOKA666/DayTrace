import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
from daytrace.personalization.diary_qt.statistics import Statistics,summarize
class StatisticsTests(unittest.TestCase):
    def test_totals_switch_and_hover(self):
        app=QApplication.instance() or QApplication([])
        widget=Statistics();widget.resize(1200,800)
        rows=[{'state':'active','interval_id':'a','start_ms':0,'end_ms':60000,'category':'工作'}]
        cards=[{'rows':rows}]
        self.assertEqual(summarize(cards+cards)[1],[('工作',60000)])
        widget.set_cards(cards,{})
        before=widget.totals[:]
        widget.buttons[1].click()
        self.assertEqual(widget.half,1)
        self.assertEqual(widget.totals,before)
        _,x,y,r=widget.geometry_values()
        self.assertEqual(widget.hit_sector(QPointF(x+r-20,y)),0)
        self.assertEqual(widget.hit_sector(QPointF(x,y)),-1)
        widget.hover=0
        widget.offset=7
        widget.set_cards(cards,{})
        self.assertEqual(widget.offset,7)
        rows[0]['end_ms']+=60000
        widget.set_cards(cards,{})
        self.assertEqual(widget.hover,0)
        self.assertEqual(widget.offset,7)
        widget.show();app.processEvents()
        self.assertFalse(widget.grab().isNull())
        widget.set_cards([],{});self.assertEqual(widget.hit_sector(QPointF(x+r-20,y)),-1)
        widget.close()
