/**
 * src/JavaBridge.java — High-performance text parsing and resume matching bridge.
 * 
 * Invoked seamlessly from Python via subprocess to execute fast string/keyword
 * extraction, resume parsing, or token analytics without external JVM dependencies.
 */
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public class JavaBridge {

    /**
     * Calculates SHA-256 canonical hash of a job posting for O(1) deduplication.
     */
    public static String computeCanonicalKey(String company, String title, String location) {
        try {
            String raw = String.format("%s|%s|%s",
                    company == null ? "" : company.trim().toLowerCase(),
                    title == null ? "" : title.trim().toLowerCase(),
                    location == null ? "" : location.trim().toLowerCase());
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(raw.getBytes(StandardCharsets.UTF_8));
            StringBuilder hexString = new StringBuilder();
            for (byte b : hash) {
                String hex = Integer.toHexString(0xff & b);
                if (hex.length() == 1) hexString.append('0');
                hexString.append(hex);
            }
            return hexString.toString();
        } catch (Exception e) {
            return "error-" + System.currentTimeMillis();
        }
    }

    /**
     * Fast keyword matching score between job description and target skills.
     */
    public static int calculateMatchScore(String jobDescription, List<String> targetSkills) {
        if (jobDescription == null || targetSkills == null || targetSkills.isEmpty()) {
            return 0;
        }
        String lowerDesc = jobDescription.toLowerCase();
        int matched = 0;
        for (String skill : targetSkills) {
            if (lowerDesc.contains(skill.trim().toLowerCase())) {
                matched++;
            }
        }
        return (int) Math.round(((double) matched / targetSkills.size()) * 100);
    }

    public static void main(String[] args) {
        if (args.length == 0) {
            System.out.println("{\"status\":\"error\",\"message\":\"No action specified. Usage: java JavaBridge <hash|score> <args...>\"}");
            System.exit(1);
        }

        String action = args[0].toLowerCase();

        try {
            switch (action) {
                case "hash":
                    String company = args.length > 1 ? args[1] : "";
                    String title = args.length > 2 ? args[2] : "";
                    String location = args.length > 3 ? args[3] : "";
                    String key = computeCanonicalKey(company, title, location);
                    System.out.println("{\"status\":\"success\",\"canonical_key\":\"" + key + "\"}");
                    break;

                case "score":
                    if (args.length < 3) {
                        System.out.println("{\"status\":\"error\",\"message\":\"Missing arguments for score. Usage: java JavaBridge score <skills-comma-separated> <jobDescription>\"}");
                        System.exit(1);
                    }
                    List<String> skills = Arrays.asList(args[1].split(","));
                    String description = args[2];
                    int score = calculateMatchScore(description, skills);
                    System.out.println("{\"status\":\"success\",\"score\":" + score + "}");
                    break;

                case "ping":
                    System.out.println("{\"status\":\"pong\",\"java_version\":\"" + System.getProperty("java.version") + "\"}");
                    break;

                default:
                    System.out.println("{\"status\":\"error\",\"message\":\"Unknown action: " + action + "\"}");
                    System.exit(1);
            }
        } catch (Exception e) {
            System.err.println("Execution failed: " + e.getMessage());
            System.exit(2);
        }
    }
}
