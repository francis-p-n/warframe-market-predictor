import sys
import os

# Add src to path so we can import predictor
sys.path.insert(0, os.path.abspath("src"))

from predictor.market.analyzer import run_analysis

def main():
    print("Running analysis...")
    report = run_analysis()
    
    output = []
    output.append(f"Warframe Market Prediction Report")
    output.append(f"Model used: {report.model_used}")
    output.append(f"Items scanned: {report.total_scanned}")
    output.append("="*50)
    
    output.append(f"\n[ BUYS ] ({len(report.buys)})")
    for sig in report.buys:
        output.append(f" - {sig.item_name} @ {sig.current_price:.0f}p ({sig.confidence*100:.0f}%)")
        
    output.append(f"\n[ SELLS ] ({len(report.sells)})")
    for sig in report.sells:
        output.append(f" - {sig.item_name} @ {sig.current_price:.0f}p ({sig.confidence*100:.0f}%)")
        
    output.append(f"\n[ HOLDS ] ({len(report.holds)})")
    for sig in report.holds:
        output.append(f" - {sig.item_name} @ {sig.current_price:.0f}p ({sig.confidence*100:.0f}%)")
        
    output_str = "\n".join(output)
    
    with open("prediction_result.txt", "w", encoding="utf-8") as f:
        f.write(output_str)
        
    print("Report saved to prediction_result.txt")

if __name__ == "__main__":
    main()
