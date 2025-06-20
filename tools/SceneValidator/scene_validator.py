#!/usr/bin/env python3
# SceneValidator - A tool to validate scene metadata and structure

import json
import os
import sys
import logging
import argparse
from typing import Dict, List, Any, Optional

# For Google Cloud and Gemini API integration
try:
    import google.generativeai as genai
    from google.cloud import storage
    HAS_GOOGLE_APIS = True
except ImportError:
    HAS_GOOGLE_APIS = False
    print("Warning: Google Cloud or Gemini API libraries not found. Some features will be limited.")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scene_validator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SceneValidator")

class SceneValidator:
    """Validates scene metadata and structure for media projects."""
    
    def __init__(self, config_path: str = "config.json"):
        """Initialize the validator with configuration."""
        self.config = self._load_config(config_path)
        self.validation_rules = self.config.get("validation_rules", {})
        self.gemini_configured = False
        
        # Initialize Gemini API if available
        if HAS_GOOGLE_APIS and "gemini_api_key" in self.config:
            try:
                genai.configure(api_key=self.config["gemini_api_key"])
                self.gemini_configured = True
                logger.info("Gemini API configured successfully")
            except Exception as e:
                logger.error(f"Failed to configure Gemini API: {e}")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from a JSON file."""
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error loading configuration: {e}")
            return {}
    
    def validate_scene_file(self, scene_file_path: str) -> Dict[str, Any]:
        """Validate a scene file against the defined rules."""
        try:
            with open(scene_file_path, 'r') as f:
                scene_data = json.load(f)
            
            # Basic structural validation
            results = {
                "file": scene_file_path,
                "valid": True,
                "errors": [],
                "warnings": [],
                "suggestions": []
            }
            
            # Check required fields
            for field in self.validation_rules.get("required_fields", []):
                if field not in scene_data:
                    results["valid"] = False
                    results["errors"].append(f"Missing required field: {field}")
            
            # Check field types
            for field, expected_type in self.validation_rules.get("field_types", {}).items():
                if field in scene_data:
                    # Simple type checking
                    if expected_type == "string" and not isinstance(scene_data[field], str):
                        results["valid"] = False
                        results["errors"].append(f"Field {field} should be a string")
                    elif expected_type == "number" and not isinstance(scene_data[field], (int, float)):
                        results["valid"] = False
                        results["errors"].append(f"Field {field} should be a number")
                    elif expected_type == "array" and not isinstance(scene_data[field], list):
                        results["valid"] = False
                        results["errors"].append(f"Field {field} should be an array")
                    elif expected_type == "object" and not isinstance(scene_data[field], dict):
                        results["valid"] = False
                        results["errors"].append(f"Field {field} should be an object")
            
            # Use Gemini API for advanced validation if available
            if self.gemini_configured and results["valid"]:
                advanced_results = self._advanced_validation_with_gemini(scene_data)
                results["suggestions"].extend(advanced_results.get("suggestions", []))
                results["warnings"].extend(advanced_results.get("warnings", []))
                
                # If advanced validation found critical issues
                if advanced_results.get("critical_issues", False):
                    results["valid"] = False
                    results["errors"].extend(advanced_results.get("errors", []))
            
            return results
            
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Error processing scene file {scene_file_path}: {e}")
            return {
                "file": scene_file_path,
                "valid": False,
                "errors": [f"Failed to process file: {str(e)}"],
                "warnings": [],
                "suggestions": []
            }
    
    def _advanced_validation_with_gemini(self, scene_data: Dict[str, Any]) -> Dict[str, Any]:
        """Use Gemini API for more advanced validation and suggestions."""
        results = {
            "suggestions": [],
            "warnings": [],
            "errors": [],
            "critical_issues": False
        }
        
        try:
            # Prepare scene data for Gemini
            scene_json = json.dumps(scene_data, indent=2)
            
            # Create a prompt for Gemini
            prompt = f"""Analyze the following media scene data for potential issues, inconsistencies, or improvements:

{scene_json}

Provide your analysis in JSON format with the following structure:
{{
  "critical_issues": [list of critical problems that make the scene invalid],
  "warnings": [list of potential problems or inconsistencies],
  "suggestions": [list of improvements or optimizations]
}}
"""
            
            # Query Gemini API
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(prompt)
            
            # Process the response
            try:
                gemini_analysis = json.loads(response.text)
                
                # Add Gemini's insights to our results
                if gemini_analysis.get("critical_issues"):
                    results["critical_issues"] = True
                    results["errors"].extend(gemini_analysis["critical_issues"])
                
                if gemini_analysis.get("warnings"):
                    results["warnings"].extend(gemini_analysis["warnings"])
                
                if gemini_analysis.get("suggestions"):
                    results["suggestions"].extend(gemini_analysis["suggestions"])
                    
            except json.JSONDecodeError:
                # If Gemini didn't return valid JSON
                results["warnings"].append("Advanced validation produced non-JSON response")
                logger.warning("Gemini response was not valid JSON")
        
        except Exception as e:
            logger.error(f"Error during advanced validation: {e}")
            results["warnings"].append(f"Advanced validation failed: {str(e)}")
        
        return results
    
    def validate_directory(self, directory_path: str) -> List[Dict[str, Any]]:
        """Validate all scene files in a directory."""
        results = []
        
        try:
            for file in os.listdir(directory_path):
                if file.endswith(".json"):
                    file_path = os.path.join(directory_path, file)
                    results.append(self.validate_scene_file(file_path))
        except FileNotFoundError:
            logger.error(f"Directory not found: {directory_path}")
        
        return results
    
    def generate_report(self, validation_results: List[Dict[str, Any]], output_file: Optional[str] = None) -> str:
        """Generate a detailed validation report."""
        report = {
            "summary": {
                "total_files": len(validation_results),
                "valid_files": sum(1 for r in validation_results if r["valid"]),
                "invalid_files": sum(1 for r in validation_results if not r["valid"]),
                "total_errors": sum(len(r["errors"]) for r in validation_results),
                "total_warnings": sum(len(r["warnings"]) for r in validation_results),
                "total_suggestions": sum(len(r["suggestions"]) for r in validation_results)
            },
            "details": validation_results
        }
        
        # Save report to file if specified
        if output_file:
            try:
                with open(output_file, 'w') as f:
                    json.dump(report, f, indent=2)
                logger.info(f"Report saved to {output_file}")
            except Exception as e:
                logger.error(f"Failed to save report: {e}")
        
        return json.dumps(report, indent=2)

def main():
    """Main entry point for command line usage."""
    parser = argparse.ArgumentParser(description="Validate scene metadata and structure")
    parser.add_argument("--config", default="config.json", help="Path to configuration file")
    parser.add_argument("--file", help="Validate a single scene file")
    parser.add_argument("--directory", help="Validate all scene files in a directory")
    parser.add_argument("--output", help="Output file for validation report")
    args = parser.parse_args()
    
    validator = SceneValidator(args.config)
    
    if args.file:
        results = [validator.validate_scene_file(args.file)]
    elif args.directory:
        results = validator.validate_directory(args.directory)
    else:
        parser.print_help()
        sys.exit(1)
    
    report = validator.generate_report(results, args.output)
    print(report)

if __name__ == "__main__":
    main()
