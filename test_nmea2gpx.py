import unittest
from pathlib import Path
import tempfile
import textwrap
import xml.etree.ElementTree as ET
from nmea2gpx import NMEASentence, RMC, GGA, GSA, VTG, process_files
import logging

class TestNMEA2GPX(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Create a temporary directory for all tests."""
        # Configure logging
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.test_dir = Path(cls.temp_dir.name)
        
        # Sample data during GPS acquisition
        cls.gps_searching_data = textwrap.dedent("""
            $GNGGA,,,,,,0,00,99.99,,,,,,*56
            $GNGSA,A,1,,,,,,,,,,,,,99.99,99.99,99.99*2E
            $GNGSA,A,1,,,,,,,,,,,,,99.99,99.99,99.99*2E
            $GNRMC,,V,,,,,,,,,,N*4D
            $GNVTG,,,,,,,,,N*2E
            $GNGGA,,,,,,0,00,99.99,,,,,,*56
            $GNGSA,A,1,,,,,,,,,,,,,99.99,99.99,99.99*2E
            $GNGSA,A,1,,,,,,,,,,,,,99.99,99.99,99.99*2E
        """).strip()

        # Sample data with valid position fixes
        cls.gps_valid_data = textwrap.dedent("""
            $GNGGA,204415.00,5222.81631,N,00453.44115,E,1,08,1.69,-13.1,M,45.9,M,,*59
            $GNGSA,A,3,07,11,06,20,,,,,,,,,5.54,1.69,5.28*1A
            $GNGSA,A,3,71,86,80,87,,,,,,,,,5.54,1.69,5.28*16
            $GNRMC,204416.00,A,5222.81586,N,00453.44075,E,0.947,,290425,,,A*6C
            $GNVTG,,T,,M,0.947,N,1.753,K,A*37
            $GNGGA,204416.00,5222.81586,N,00453.44075,E,1,08,1.69,-13.3,M,45.9,M,,*50
            $GNGSA,A,3,07,11,06,20,,,,,,,,,5.54,1.69,5.27*15
            $GNGSA,A,3,71,86,80,87,,,,,,,,,5.54,1.69,5.27*19
            $GNRMC,204417.00,A,5222.81530,N,00453.44076,E,0.654,,290425,,,A*6E
            $GNVTG,,T,,M,0.654,N,1.212,K,A*3A
        """).strip()

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary directory after all tests."""
        cls.temp_dir.cleanup()

    def setUp(self):
        """Clean up any files before each test."""
        # Remove any existing files in the test directory
        for file in self.test_dir.glob('*'):
            file.unlink()

    def test_gps_searching_sentences(self):
        """Test that sentences during GPS acquisition are properly rejected."""
        # Test RMC sentence
        rmc_line = "$GNRMC,,V,,,,,,,,,,N*4D"
        nmea = NMEASentence.parse(rmc_line)
        self.assertTrue(nmea.is_valid)  # Checksum is valid
        self.assertIsInstance(nmea, RMC)
        self.assertFalse(nmea.status)  # Data is not valid (V)
        self.assertIsNone(nmea.latitude)
        self.assertIsNone(nmea.longitude)
        
        # Test GGA sentence
        gga_line = "$GNGGA,,,,,,0,00,99.99,,,,,,*56"
        nmea = NMEASentence.parse(gga_line)
        self.assertTrue(nmea.is_valid)  # Checksum is valid
        self.assertIsInstance(nmea, GGA)
        self.assertEqual(nmea.fix_quality, 0)  # No fix
        self.assertIsNone(nmea.latitude)
        self.assertIsNone(nmea.longitude)
    
    def test_gps_searching_file(self):
        """Test that a file with only GPS searching data produces no output points."""
        # Create input file
        input_file = self.test_dir / "searching.nmea"
        input_file.write_text(self.gps_searching_data)
        
        # Create output file
        output_gpx = self.test_dir / "output.gpx"
        
        # Process the file
        process_files([input_file], output_gpx)
        
        # Check that output file exists
        self.assertTrue(output_gpx.exists())
        
        # Parse GPX and verify no trackpoints
        tree = ET.parse(output_gpx)
        root = tree.getroot()
        trackpoints = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        self.assertEqual(len(trackpoints), 0)

    def test_valid_gps_data(self):
        """Test processing of valid GPS data with actual position fixes."""
        # Create input file
        input_file = self.test_dir / "valid.nmea"
        input_file.write_text(self.gps_valid_data)
        
        # Create output file
        output_gpx = self.test_dir / "output.gpx"
        
        # Process the file
        process_files([input_file], output_gpx)
        
        # Check that output file exists
        self.assertTrue(output_gpx.exists())
        
        # Parse GPX and verify trackpoints
        tree = ET.parse(output_gpx)
        root = tree.getroot()
        
        # Should have 2 trackpoints (from RMC/GGA pairs)
        trackpoints = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        self.assertEqual(len(trackpoints), 2)
        
        # Check first trackpoint
        trkpt = trackpoints[0]
        self.assertAlmostEqual(float(trkpt.get('lat')), 52.38026433)  # 52 + 22.81586/60
        self.assertAlmostEqual(float(trkpt.get('lon')), 4.89067917)   # 4 + 53.44075/60
        
        # Check elevation
        ele = trkpt.find(".//{http://www.topografix.com/GPX/1/1}ele")
        self.assertAlmostEqual(float(ele.text), -13.1)
        
        # Check timestamp
        time = trkpt.find(".//{http://www.topografix.com/GPX/1/1}time")
        self.assertIn('2025-04-29T20:44:', time.text)

if __name__ == '__main__':
    unittest.main() 